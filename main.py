import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
from datetime import datetime, timedelta
import logging
import random
import string
import pytz
import asyncio
import io
import zipfile
import uuid
import html as html_lib
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional, List, Dict, Tuple, Set

# ═══════════════════════════════════════════════════════
#   ADMIN KONFIGURATION
# ═══════════════════════════════════════════════════════
ADMIN_USER_IDS = [1211683189186105434]

GERMANY_TZ = pytz.timezone("Europe/Berlin")


def get_now() -> datetime:
    return datetime.now(GERMANY_TZ)


def make_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return GERMANY_TZ.localize(dt)
    return dt.astimezone(GERMANY_TZ)


# ═══════════════════════════════════════════════════════
#   LOGGING
# ═══════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("insurance_bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("InsuranceGuard")

# ═══════════════════════════════════════════════════════
#   BOT SETUP
# ═══════════════════════════════════════════════════════
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "insurance_data.json"
CONFIG_FILE = "bot_config.json"

# ═══════════════════════════════════════════════════════
#   STANDARD-KONFIGURATION
# ═══════════════════════════════════════════════════════
DEFAULT_CONFIG = {
    "log_channel_id": None,
    "kundenkontakt_category_id": None,
    "schadensmeldung_category_id": None,
    "auszahlung_channel_id": None,
    "kundenkontakt_channel_id": None,
    "schadensmeldung_channel_id": None,
    "dokumentation_channel_id": None,
    "steuer_prozent": 3.0,
    "guild_modules": {},
    "insurance_types": {
        "Krankenversicherung (Privat)": {
            "price": 10000.00,
            "role": "Krankenversicherung (Privat)",
            "auszahlung_limit": 20000.00,
            "enabled": True,
        },
        "Haftpflichtversicherung": {
            "price": 10000.00,
            "role": "Haftpflichtversicherung",
            "auszahlung_limit": 20000.00,
            "enabled": True,
        },
        "Hausratversicherung": {
            "price": 10000.00,
            "role": "Hausratversicherung",
            "auszahlung_limit": 20000.00,
            "enabled": True,
        },
        "Kfz-Versicherung": {
            "price": 7500.00,
            "role": "Kfz-Versicherung",
            "auszahlung_limit": 15000.00,
            "enabled": True,
        },
        "Rechtsschutzversicherung": {
            "price": 5000.00,
            "role": "Rechtsschutzversicherung",
            "auszahlung_limit": 10000.00,
            "enabled": True,
        },
        "Bußgeldversicherung": {
            "price": 10000.00,
            "role": "Bußgeldversicherung",
            "auszahlung_limit": 20000.00,
            "enabled": True,
        },
    },
}


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        for key, val in DEFAULT_CONFIG.items():
            if key not in loaded:
                loaded[key] = val
        if "insurance_types" not in loaded:
            loaded["insurance_types"] = DEFAULT_CONFIG["insurance_types"]
        return loaded
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


config = load_config()


def get_insurance_types() -> dict:
    return {
        k: v
        for k, v in config.get("insurance_types", {}).items()
        if v.get("enabled", True)
    }


def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        for key in (
            "schadensmeldungen",
            "pending_auszahlungen",
            "customers",
            "invoices",
        ):
            if key not in d:
                d[key] = {}
        if "logs" not in d:
            d["logs"] = []
        if "ticket_channels" not in d:
            d["ticket_channels"] = {}
        # Neue Datenfelder
        if "schaden_historie" not in d:
            d["schaden_historie"] = {}
        if "ticket_stats" not in d:
            d["ticket_stats"] = []
        if "mitarbeiter_status" not in d:
            d["mitarbeiter_status"] = {}
        if "blacklist" not in d:
            d["blacklist"] = {}  # {customer_id: {grund, added_by, added_at}}
        return d
    return {
        "customers": {},
        "invoices": {},
        "logs": [],
        "schadensmeldungen": {},
        "pending_auszahlungen": {},
        "ticket_channels": {},
        "schaden_historie": {},
        "ticket_stats": [],
        "mitarbeiter_status": {},
        "blacklist": {},
    }


def save_data(d: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=4, ensure_ascii=False)


data = load_data()


# ═══════════════════════════════════════════════════════
#   ID GENERATOREN
# ═══════════════════════════════════════════════════════
def generate_customer_id() -> str:
    return f"VN-{get_now().strftime('%y')}{''.join(random.choices(string.digits, k=6))}"


def generate_invoice_id() -> str:
    return f"RE-{get_now().strftime('%y%m')}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=4))}"


def generate_schaden_id() -> str:
    return f"SM-{get_now().strftime('%y%m')}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=4))}"


def generate_auszahlung_id() -> str:
    return f"AZ-{get_now().strftime('%y%m')}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=4))}"


# ═══════════════════════════════════════════════════════
#   FARBEN & KONSTANTEN —  DVG Corporate Design
# ═══════════════════════════════════════════════════════
#  Farben dienen als Statussignal (farbiger Rand der Container):
#  Blau = Standard, Grün = Erfolg, Orange = Warnung, Rot = Fehler.
EMBED_COLOR = 0x3D4EC5  # DVG-Blau als Standard-Akzent der Container

# Legacy-Aliase (werden intern nicht mehr direkt genutzt, aber falls externe
# Referenzen bestehen bleiben sie vorhanden)
EMBED_SUCCESS = 0x57F287
EMBED_WARNING = 0xE67E22
EMBED_ERROR = 0xD83C3E

# Legacy-Aliase
COLOR_PRIMARY = EMBED_COLOR
COLOR_SUCCESS = EMBED_SUCCESS
COLOR_WARNING = EMBED_WARNING
COLOR_ERROR = EMBED_ERROR
COLOR_INFO = EMBED_COLOR
COLOR_DAMAGE = EMBED_COLOR
COLOR_CLAIM = EMBED_COLOR
DESIGN_COLOR = EMBED_COLOR  # Standard-Akzentfarbe der Container

# DVG-Akzentfarben
DVG_BLUE = 0x3D4EC5
DVG_RED = 0xB82238
DVG_PURPLE = 0x5A3D8A

# DVG-Akzentfarben (für spätere Nutzung in Visualisierungen)
DVG_BLUE = 0x3D4EC5
DVG_RED = 0xB82238
DVG_PURPLE = 0x5A3D8A

# Tuple mit Role-IDs für Multi-Server-Support
MITARBEITER_ROLE_ID = (1408800823571513537, 1495094890298871874)
LEITUNGSEBENE_ROLE_ID = (1408797319134187601, 1495094890307256559)
FIRMENKONTOROLLE_ROLE_ID = (1474047313025433684, 1495094890323906564)
KUNDEN_ROLE_NAME = "Versicherungsnehmer"

FOOTER_ICON = "https://images-ext-1.discordapp.net/external/ymktlgwOVtfgthFaYKgqoi_FnuvFhkhYFAT5Zri83Kw/%3Fsize%3D4096/https/cdn.discordapp.com/avatars/1494338524705718412/0bd737c851d6993ec6a38563bc3f2ee0.png?format=webp&quality=lossless&width=230&height=230"
AUTOMOD_ICON = "https://media.discordapp.net/attachments/1473692441726029874/1473692787156455474/1072-automod.png?ex=699722dc&is=6995d15c&hm=08ad340d3673e1f1076cbf73d235ea3b0e8ef10b07abb8d24ea66d85c6b59edb&=&format=webp&quality=lossless&width=250&height=250"
AUTHOR_ICON = "https://images-ext-1.discordapp.net/external/oaegfwZ-7BSrD3Q4oHp7bYcKEU4bzeHPyYOn-ePhVNM/%3Fsize%3D4096/https/cdn.discordapp.com/icons/1408794976615268384/70aeea0005d728278f7f78e94b580d45.png?format=webp&quality=lossless&width=624&height=624"
FOOTER_TEXT = "Copyright © InsuranceGuard v4"
AUTHOR_NAME = "Deutsche Versicherungsgesellschaft"


# ═══════════════════════════════════════════════════════
#   EHRN DESIGN-SYSTEM — Components V2 (discord.py 2.6+)
# ═══════════════════════════════════════════════════════
#  Jede Bot-Nachricht ist ein Container mit farbigem Rand:
#  Überschrift → Trennlinie → Inhalt → (Buttons) → Hinweis → Fußzeile.
#  Fehler: roter Container ohne Fußzeile. Niemand wird gepingt, außer
#  über eine eigene Ping-Zeile über dem Container (siehe ev(..., ping=...)).
#  Bestehende discord.Embed-Objekte werden von ev() automatisch umgewandelt.
# ═══════════════════════════════════════════════════════
DESIGN_FOOTER = "**DVG - Deutsche Versicherungsgesellschaft**"
MAX_TEXT = 3800  # Discord erlaubt 4.000 Zeichen Text pro Nachricht

SEPARATOR = object()
NO_MENTIONS = discord.AllowedMentions.none()
PING_MENTIONS = discord.AllowedMentions(
    everyone=False, users=True, roles=True, replied_user=False
)


class DEmbed(discord.Embed):
    """Embed mit zusätzlichen Design-Flags (big = ##-Überschrift für Dokumente/Panels)."""

    big: bool = False


def _unquote(text) -> str:
    """Entfernt die alten Zitat-Präfixe '> ' (altes Embed-Design) zeilenweise."""
    if text is None:
        return ""
    lines = [re.sub(r"^\s*>\s?", "", ln) for ln in str(text).split("\n")]
    return "\n".join(lines).strip()


def _field_text(name: str, value: str) -> str:
    name = str(name or "").strip()
    value = _unquote(value)
    if not value:
        return f"**{name}**" if name else ""
    if not name or name in ("\u200b", "‎"):
        return value
    if "\n" in value or len(value) > 70 or value.startswith("```"):
        return f"**{name}**\n{value}"
    if name.endswith(("!", ":", "?")) or ":" in name:
        return f"**{name}** {value}"
    return f"**{name}:** {value}"


def _ts_style(dt, style="f") -> str:
    return f"<t:{int(dt.timestamp())}:{style}>"


def _split_rows(items) -> list:
    """Verteilt Buttons/Menüs auf Action Rows (Menü = eigene Zeile, max. 5 Buttons)."""
    rows, current = [], None
    for item in items:
        if isinstance(item, discord.ui.Select):
            rows.append(discord.ui.ActionRow(item))
            current = None
            continue
        if current is None or len(current.children) >= 5:
            current = discord.ui.ActionRow()
            rows.append(current)
        current.add_item(item)
    return rows[:5]


def build_container(
    embed: Optional[discord.Embed],
    items=None,
    *,
    extra_files: Optional[List[str]] = None,
) -> discord.ui.Container:
    """Wandelt ein (altes) Embed in einen EHRN-Container um."""
    color = DESIGN_COLOR
    heading = ""
    body = ""
    hint = ""
    show_footer = True
    stamp = None

    if embed is not None:
        if embed.color is not None and embed.color.value is not None:
            color = embed.color.value
        is_error = color == COLOR_ERROR
        show_footer = not is_error
        big = bool(getattr(embed, "big", False))
        if embed.title:
            heading = f"{'##' if big else '###'} {str(embed.title).strip()}"
        desc = _unquote(embed.description)
        field_blocks = [
            t for t in (_field_text(f.name, f.value) for f in embed.fields) if t
        ]
        parts = []
        if desc:
            parts.append(desc)
        if field_blocks:
            parts.append("\n\n".join(field_blocks))
        body = "\n\n".join(parts)
        if embed.footer and embed.footer.text and embed.footer.text != FOOTER_TEXT:
            hint = f"-# {embed.footer.text.strip()}"
        if embed.timestamp and show_footer:
            stamp = embed.timestamp

    # Sicherheitsnetz: Discord erlaubt max. 4.000 Zeichen Text je Nachricht
    footer = f"-# {DESIGN_FOOTER}" + (f" · {_ts_style(stamp)}" if stamp else "")
    budget = MAX_TEXT - len(heading) - len(hint) - len(footer) - 40
    if len(body) > budget:
        cut = body[:budget].rsplit("\n", 1)[0]
        body = cut + "\n-# … weitere Einträge gekürzt"

    container = discord.ui.Container(accent_colour=color)
    if heading:
        container.add_item(discord.ui.TextDisplay(heading))
    if heading and (body or items):
        container.add_item(
            discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small)
        )
    if body:
        container.add_item(discord.ui.TextDisplay(body))
    for fname in extra_files or []:
        container.add_item(discord.ui.File(f"attachment://{fname}"))
    rows = _split_rows(items or [])
    if rows:
        if body:
            container.add_item(
                discord.ui.Separator(
                    visible=True, spacing=discord.SeparatorSpacing.small
                )
            )
        for row in rows:
            container.add_item(row)
    if hint:
        container.add_item(discord.ui.TextDisplay(hint))
    if show_footer:
        container.add_item(discord.ui.TextDisplay(footer))
    return container


class EView(discord.ui.LayoutView):
    """
    Ersatz für discord.ui.View: Buttons/Menüs werden wie gewohnt per
    @discord.ui.button / add_item angelegt, aber im Container gerendert.
    Der Inhalt (Embed) wird beim Senden über ev(embed, view) übergeben.
    """

    __ev_specs__: tuple = ()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        specs = []
        for base in reversed(cls.__mro__):
            for member in base.__dict__.values():
                if hasattr(member, "__discord_ui_model_type__") and not getattr(
                    member, "__discord_ui_parent__", None
                ):
                    specs.append(member)
        cls.__ev_specs__ = tuple(specs)

    def __init__(self, *, timeout: Optional[float] = 180.0):
        super().__init__(timeout=timeout)
        self._ev_items: list = []
        self._ev_ping: Optional[str] = None
        for func in type(self).__ev_specs__:
            item = func.__discord_ui_model_type__(**func.__discord_ui_model_kwargs__)
            item.callback = self._make_callback(func, item)
            self._ev_items.append(item)

    def _make_callback(self, func, item):
        async def _cb(interaction: discord.Interaction):
            await func(self, interaction, item)

        return _cb

    # — View-kompatible API (statt .children bitte .controls verwenden) —
    @property
    def controls(self) -> list:
        """Alle Buttons/Menüs dieser Ansicht (entspricht dem alten View.children)."""
        return list(self._ev_items)

    def add_item(self, item):
        self._ev_items.append(item)
        return self

    def remove_item(self, item):
        if item in self._ev_items:
            self._ev_items.remove(item)
        return self

    def clear_items(self):
        self._ev_items.clear()
        return self

    def render(
        self,
        embed: Optional[discord.Embed] = None,
        ping: Optional[str] = None,
        files: Optional[List[str]] = None,
    ):
        """Baut den Container neu auf (Embed + aktuelle Buttons/Menüs)."""
        discord.ui.LayoutView.clear_items(self)
        if ping:
            discord.ui.LayoutView.add_item(self, discord.ui.TextDisplay(ping))
        discord.ui.LayoutView.add_item(
            self, build_container(embed, self._ev_items, extra_files=files)
        )
        return self


def _plain_view() -> EView:
    return EView(timeout=None)


def ev(
    embed: Optional[discord.Embed] = None,
    view: Optional[EView] = None,
    ping: Optional[str] = None,
    file: Optional[str] = None,
) -> dict:
    """Kwargs für send()/send_message()/followup.send()/edit(): view=… + allowed_mentions."""
    layout = view if view is not None else _plain_view()
    if not isinstance(layout, EView):
        raise TypeError("ev() erwartet eine EView")
    layout.render(embed, ping, [file] if file else None)
    return {"view": layout, "allowed_mentions": PING_MENTIONS if ping else NO_MENTIONS}


_ERROR_HINTS = re.compile(
    r"fehler|ungültig|nicht gefunden|nicht konfiguriert|überschreit|reicht nicht|"
    r"muss > |nicht möglich|nicht gesetzt|ausgeschöpft|bereits bearbeitet|nicht mehr",
    re.I,
)


def ev_text(
    text: str, ping: Optional[str] = None, error: Optional[bool] = None
) -> dict:
    """Kurze Textantwort im Container-Design (Fehler = roter Container ohne Fußzeile)."""
    text = str(text).strip()
    if error is None:
        error = bool(_ERROR_HINTS.search(text))
    e = DEmbed(description=text, color=COLOR_ERROR if error else DESIGN_COLOR)
    if error:
        e.title = None
    return ev(e, ping=ping)


def _walk_components(components):
    for comp in components or []:
        yield comp
        for attr in ("children", "components"):
            sub = getattr(comp, attr, None)
            if sub:
                yield from _walk_components(sub)
        acc = getattr(comp, "accessory", None)
        if acc is not None:
            yield from _walk_components([acc])


def message_custom_ids(message: discord.Message) -> set:
    """Alle custom_ids der Buttons/Menüs einer Nachricht (klassisch und V2)."""
    return {
        getattr(c, "custom_id", None)
        for c in _walk_components(message.components)
        if getattr(c, "custom_id", None)
    }


def ev_msg(message: discord.Message, view: EView) -> dict:
    """
    Kwargs zum Bearbeiten einer BESTEHENDEN Nachricht, bei der nur die Buttons
    geändert werden (Text bleibt erhalten). Funktioniert für V2-Nachrichten und
    für alte Embed-Nachrichten aus der Zeit vor dem Design-Update.
    """
    kwargs: dict = {"allowed_mentions": NO_MENTIONS}
    if message.flags.components_v2:
        layout = discord.ui.LayoutView.from_message(message, timeout=view.timeout)
        for top in list(layout.children):
            if isinstance(top, discord.ui.Container):
                for child in list(top.children):
                    if isinstance(child, discord.ui.ActionRow):
                        top.remove_item(child)
                rows = _split_rows(view.controls)
                # Reihen vor Hinweis/Fußzeile (die letzten TextDisplays) einfügen
                texts_tail = []
                while (
                    top.children
                    and isinstance(top.children[-1], discord.ui.TextDisplay)
                    and len(texts_tail) < 2
                    and top.children[-1].content.startswith("-#")
                ):
                    texts_tail.insert(0, top.children[-1])
                    top.remove_item(top.children[-1])
                if rows:
                    if not (
                        top.children
                        and isinstance(top.children[-1], discord.ui.Separator)
                    ):
                        top.add_item(
                            discord.ui.Separator(
                                visible=True, spacing=discord.SeparatorSpacing.small
                            )
                        )
                    for row in rows:
                        top.add_item(row)
                for t in texts_tail:
                    top.add_item(t)
                break
        kwargs["view"] = layout
        return kwargs
    # Alte Embed-Nachricht → in das neue Design überführen
    embed = message.embeds[0] if message.embeds else None
    kwargs.update(ev(embed, view))
    kwargs["embeds"] = []
    kwargs["content"] = None
    return kwargs


def v2_edit(
    message: discord.Message,
    embed: discord.Embed,
    view: Optional[EView] = None,
    ping: Optional[str] = None,
) -> dict:
    """Kwargs zum vollständigen Neu-Rendern einer Nachricht (auch alte Embed-Nachrichten)."""
    kwargs = ev(embed, view, ping)
    kwargs["allowed_mentions"] = NO_MENTIONS  # Bearbeitungen pingen nie erneut
    if message.embeds or message.content or not message.flags.components_v2:
        kwargs["embeds"] = []
        kwargs["content"] = None
    return kwargs


def restyle(
    message: discord.Message,
    fields: Optional[list] = None,
    color: Optional[int] = None,
    drop_controls: bool = True,
) -> dict:
    """
    Ändert eine bestehende Bot-Nachricht (Status-Updates).
    fields: Liste von (Präfix, Name, Wert) — ersetzt den Feld-Block, der mit **Präfix
    beginnt, oder hängt ihn an. Funktioniert für V2-Nachrichten und alte Embed-Nachrichten.
    """
    fields = fields or []
    if message.flags.components_v2:
        layout = discord.ui.LayoutView.from_message(message, timeout=None)
        for top in layout.children:
            if not isinstance(top, discord.ui.Container):
                continue
            if color is not None:
                top.accent_colour = color
            if drop_controls:
                for child in list(top.children):
                    if isinstance(child, discord.ui.ActionRow):
                        top.remove_item(child)
            texts = [c for c in top.children if isinstance(c, discord.ui.TextDisplay)]
            body_candidates = [
                t for t in texts if not t.content.startswith(("#", "-#"))
            ]
            body = (
                max(body_candidates, key=lambda t: len(t.content))
                if body_candidates
                else None
            )
            for prefix, name, value in fields:
                new_block = _field_text(name, value)
                done = False
                for t in texts:
                    blocks = t.content.split("\n\n")
                    for i, blk in enumerate(blocks):
                        if blk.lstrip().startswith(f"**{prefix}"):
                            blocks[i] = new_block
                            t.content = "\n\n".join(blocks)
                            done = True
                            break
                    if done:
                        break
                if not done and body is not None:
                    body.content = f"{body.content}\n\n{new_block}"
            break
        return {"view": layout, "allowed_mentions": NO_MENTIONS}
    # Alte Embed-Nachricht → ins neue Design überführen
    emb = DEmbed.from_dict(message.embeds[0].to_dict()) if message.embeds else DEmbed()
    if color is not None:
        emb.color = color
    for prefix, name, value in fields:
        idx = next(
            (i for i, f in enumerate(emb.fields) if str(f.name).startswith(prefix)),
            None,
        )
        if idx is None:
            emb.add_field(name=name, value=value, inline=False)
        else:
            emb.set_field_at(idx, name=name, value=value, inline=False)
    kw = ev(emb)
    kw["embeds"] = []
    kw["content"] = None
    kw["allowed_mentions"] = NO_MENTIONS
    return kw


def register_persistent(view: "EView") -> None:
    """Registriert eine persistente Ansicht (Buttons funktionieren nach Neustarts weiter)."""
    view.render(DEmbed(title="Persistente Ansicht"))
    bot.add_view(view)


# ═══════════════════════════════════════════════════════
#   HILFSFUNKTIONEN
# ═══════════════════════════════════════════════════════
async def send_to_log_channel(
    guild: discord.Guild,
    embed: discord.Embed,
    view: Optional["EView"] = None,
    file: Optional[discord.File] = None,
):
    if config.get("log_channel_id"):
        try:
            ch = guild.get_channel(config["log_channel_id"])
            if ch:
                if file:
                    await ch.send(file=file, **ev(embed, view=view, file=file.filename))
                else:
                    await ch.send(**ev(embed, view=view))
        except Exception as e:
            logger.error(f"Log-Channel Fehler: {e}")


# ── DVG Embed-Builder ────────────────────────────────────────────────────────
def dvg_embed(title: str, description: str = "", big: bool = False) -> DEmbed:
    """
    Erstellt ein DVG-Embed-Objekt, das ev() automatisch in einen EHRN-Container
    umwandelt (Überschrift, Trennlinie, Inhalt, Fußzeile).
    """
    kwargs: dict = {"title": title, "color": EMBED_COLOR, "timestamp": get_now()}
    if description:
        kwargs["description"] = description
    e = DEmbed(**kwargs)
    e.big = big
    return e


async def send_to_dokumentation_channel(
    guild: discord.Guild, mitarbeiter: discord.Member, vorgang: str, anliegen: str
):
    """Sendet einen strukturierten Vorgangsvermerk in den Dokumentationskanal."""
    dok_id = config.get("dokumentation_channel_id")
    if not dok_id:
        return
    ch = guild.get_channel(dok_id)
    if not ch:
        return
    try:
        e = DEmbed(title="Dokumentation", color=EMBED_COLOR, timestamp=get_now())
        e.add_field(
            name="Mitarbeiter",
            value=f"> <:member:1522597880437932112> {mitarbeiter.mention}",
            inline=False,
        )
        e.add_field(
            name="Vorgang",
            value=f"> <:3084channelsandroles:1522597765794758810> {vorgang}",
            inline=False,
        )
        e.add_field(name="Anliegen", value=f"> {anliegen}", inline=False)
        await ch.send(**ev(e))
    except Exception as ex:
        logger.error(f"Dokumentationskanal Fehler: {ex}")


def create_backup() -> Optional[str]:
    try:
        os.makedirs("backups", exist_ok=True)
        ts = get_now().strftime("%Y%m%d_%H%M%S")
        path = f"backups/backup_{ts}.json"
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=4, ensure_ascii=False)
        return path
    except Exception as e:
        logger.error(f"Backup-Fehler: {e}")
        return None


# ═══════════════════════════════════════════════════════
#   TRANSCRIPT — HTML-DATEI (Discord-Style)
# ═══════════════════════════════════════════════════════
#  Beim Schließen eines Tickets wird ein vollständiges Transkript als
#  HTML-Datei erzeugt und als Anhang gesendet (kein Link, kein Web-Server).
#  Enthalten sind alle Nachrichten: Text, Anhänge, Embeds, Container,
#  Antworten, Sticker, Systemnachrichten und weitergeleitete Nachrichten.
# ═══════════════════════════════════════════════════════
_RE_CODEBLOCK = re.compile(r"```(?:[a-zA-Z0-9_+-]*\n)?(.*?)```", re.S)


def _esc(text) -> str:
    """HTML-escapet einen String."""
    return html_lib.escape(str(text if text is not None else ""))


def _fmt_ts(unix: int, style: str = "f") -> str:
    dt = datetime.fromtimestamp(unix, GERMANY_TZ)
    if style == "d":
        return dt.strftime("%d.%m.%Y")
    if style == "t":
        return dt.strftime("%H:%M")
    if style == "T":
        return dt.strftime("%H:%M:%S")
    return dt.strftime("%d.%m.%Y %H:%M")


def _inline_html(text: str, guild: Optional[discord.Guild]) -> str:
    """Inline-Markdown + Erwähnungen + Emojis + Zeitstempel → HTML."""
    spans: List[str] = []

    def _stash(m):
        spans.append(f"<code>{m.group(1)}</code>")
        return f"\x00{len(spans) - 1}\x00"

    s = html_lib.escape(str(text))
    s = re.sub(r"`([^`\n]+)`", _stash, s)

    def _user(m):
        uid = int(m.group(1))
        member = guild.get_member(uid) if guild else None
        return f'<span class="mention">@{_esc(member.display_name) if member else "Nutzer"}</span>'

    def _role(m):
        role = guild.get_role(int(m.group(1))) if guild else None
        return f'<span class="mention">@{_esc(role.name) if role else "Rolle"}</span>'

    def _chan(m):
        ch = guild.get_channel_or_thread(int(m.group(1))) if guild else None
        return f'<span class="mention">#{_esc(ch.name) if ch else "kanal"}</span>'

    s = re.sub(r"&lt;@!?(\d+)&gt;", _user, s)
    s = re.sub(r"&lt;@&amp;(\d+)&gt;", _role, s)
    s = re.sub(r"&lt;#(\d+)&gt;", _chan, s)
    s = re.sub(
        r"&lt;t:(\d+)(?::([a-zA-Z]))?&gt;",
        lambda m: f'<span class="mention">{_fmt_ts(int(m.group(1)), m.group(2) or "f")}</span>',
        s,
    )
    s = re.sub(
        r"&lt;(a?):([A-Za-z0-9_]+):(\d+)&gt;",
        lambda m: (
            f'<img class="emoji" alt=":{m.group(2)}:" '
            f'src="https://cdn.discordapp.com/emojis/{m.group(3)}.{"gif" if m.group(1) else "png"}?size=32">'
        ),
        s,
    )
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"__(.+?)__", r"<u>\1</u>", s)
    s = re.sub(r"~~(.+?)~~", r"<s>\1</s>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"(?<![\w])_(?!\s)(.+?)(?<!\s)_(?![\w])", r"<em>\1</em>", s)
    s = re.sub(
        r"(https?://[^\s<]+)",
        r'<a href="\1" target="_blank" rel="noopener">\1</a>',
        s,
    )
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], s)


def _lines_html(text: str, guild: Optional[discord.Guild]) -> str:
    out = []
    for ln in text.split("\n"):
        if not ln.strip():
            out.append('<div class="gap"></div>')
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", ln)
        if m:
            out.append(
                f'<div class="h{len(m.group(1))}">{_inline_html(m.group(2), guild)}</div>'
            )
            continue
        m = re.match(r"^-#\s+(.*)$", ln)
        if m:
            out.append(f'<div class="sub">{_inline_html(m.group(1), guild)}</div>')
            continue
        m = re.match(r"^>\s?(.*)$", ln)
        if m:
            out.append(f'<div class="quote">{_inline_html(m.group(1), guild)}</div>')
            continue
        out.append(f'<div class="line">{_inline_html(ln, guild)}</div>')
    return "".join(out)


def _md_html(text: Optional[str], guild: Optional[discord.Guild] = None) -> str:
    """Discord-Markdown → HTML (inkl. Codeblöcken)."""
    if not text:
        return ""
    out, pos = [], 0
    for m in _RE_CODEBLOCK.finditer(text):
        out.append(_lines_html(text[pos : m.start()], guild))
        out.append(f'<pre class="code">{_esc(m.group(1).strip(chr(10)))}</pre>')
        pos = m.end()
    out.append(_lines_html(text[pos:], guild))
    return "".join(out)


def _color_hex(value, default: str = "#4e5058") -> str:
    try:
        if value is None:
            return default
        raw = value.value if hasattr(value, "value") else int(value)
        return f"#{raw:06x}"
    except Exception:
        return default


def _render_embed_html(
    embed: discord.Embed, guild: Optional[discord.Guild] = None
) -> str:
    """Klassische Embeds (z. B. von anderen Bots oder aus älteren Tickets)."""
    parts: List[str] = []
    if embed.author and embed.author.name:
        parts.append(f'<div class="embed-author">{_esc(embed.author.name)}</div>')
    if embed.title:
        if embed.url:
            parts.append(
                f'<a href="{_esc(embed.url)}" target="_blank" class="embed-title-link">{_esc(embed.title)}</a>'
            )
        else:
            parts.append(f'<div class="embed-title">{_esc(embed.title)}</div>')
    if embed.description:
        parts.append(
            f'<div class="embed-desc">{_md_html(embed.description, guild)}</div>'
        )
    inline_group: List[str] = []
    for field in embed.fields:
        fh = (
            f'<div class="field-block{"--inline" if field.inline else ""}">'
            f'<div class="field-name">{_inline_html(field.name, guild)}</div>'
            f'<div class="field-value">{_md_html(field.value, guild)}</div></div>'
        )
        if field.inline:
            inline_group.append(fh)
        else:
            if inline_group:
                parts.append(f'<div class="field-row">{"".join(inline_group)}</div>')
                inline_group = []
            parts.append(fh)
    if inline_group:
        parts.append(f'<div class="field-row">{"".join(inline_group)}</div>')
    if embed.image and embed.image.url:
        parts.append(
            f'<img class="embed-img" src="{_esc(embed.image.url)}" loading="lazy">'
        )
    if embed.footer and embed.footer.text:
        parts.append(f'<div class="embed-footer">{_esc(embed.footer.text)}</div>')
    return f'<div class="embed" style="border-left:4px solid {_color_hex(embed.color, "#5865f2")}">{"".join(parts)}</div>'


def _render_component_html(comp, guild: Optional[discord.Guild] = None) -> str:
    """Components V2 (Container, Text, Trennlinien, Buttons …) → HTML."""
    kind = getattr(getattr(comp, "type", None), "name", "")
    if kind == "container":
        inner = "".join(_render_component_html(c, guild) for c in comp.children)
        return f'<div class="embed" style="border-left:4px solid {_color_hex(getattr(comp, "accent_colour", None))}">{inner}</div>'
    if kind == "text_display":
        return f'<div class="cv-text">{_md_html(comp.content, guild)}</div>'
    if kind == "separator":
        return '<hr class="sep">'
    if kind == "section":
        inner = "".join(_render_component_html(c, guild) for c in comp.children)
        acc = _render_component_html(comp.accessory, guild) if comp.accessory else ""
        return f'<div class="cv-section"><div>{inner}</div>{acc}</div>'
    if kind == "thumbnail":
        url = getattr(comp.media, "url", "")
        return f'<img class="thumb" src="{_esc(url)}" loading="lazy">' if url else ""
    if kind == "media_gallery":
        return "".join(
            f'<img class="embed-img" src="{_esc(it.media.url)}" loading="lazy">'
            for it in comp.items
            if getattr(it.media, "url", None)
        )
    if kind == "file":
        name = getattr(comp, "name", None) or "Datei"
        url = getattr(comp.media, "url", "")
        return f'<div class="attachment"><a href="{_esc(url)}" target="_blank">📎 {_esc(name)}</a></div>'
    if kind == "action_row":
        chips = "".join(_render_component_html(c, guild) for c in comp.children)
        return f'<div class="row">{chips}</div>'
    if kind == "button":
        label = _esc(getattr(comp, "label", None) or "")
        emoji = getattr(comp, "emoji", None)
        emo = f"{_esc(str(emoji))} " if emoji and not getattr(emoji, "id", None) else ""
        return f'<span class="btn{" off" if getattr(comp, "disabled", False) else ""}">{emo}{label}</span>'
    if kind in (
        "select",
        "user_select",
        "role_select",
        "mentionable_select",
        "channel_select",
    ):
        return f'<span class="btn off">{_esc(getattr(comp, "placeholder", None) or "Auswahlmenü")}</span>'
    return ""


def _render_body_html(source, guild: Optional[discord.Guild]) -> str:
    """Rendert Inhalt, Anhänge, Embeds und Komponenten einer Nachricht (oder eines Snapshots)."""
    body = ""
    if getattr(source, "content", None):
        body += f'<div class="msg-text">{_md_html(source.content, guild)}</div>'
    for att in getattr(source, "attachments", []) or []:
        ctype = getattr(att, "content_type", "") or ""
        if ctype.startswith("image/"):
            body += (
                f'<div class="attachment"><a href="{_esc(att.url)}" target="_blank">'
                f'<img class="embed-img" src="{_esc(att.url)}" loading="lazy" alt="{_esc(att.filename)}"></a></div>'
            )
        else:
            body += f'<div class="attachment"><a href="{_esc(att.url)}" target="_blank">📎 {_esc(att.filename)}</a></div>'
    for emb in getattr(source, "embeds", []) or []:
        body += _render_embed_html(emb, guild)
    for comp in getattr(source, "components", []) or []:
        body += _render_component_html(comp, guild)
    for st in getattr(source, "stickers", []) or []:
        body += f'<div class="attachment">Sticker: {_esc(getattr(st, "name", "Sticker"))}</div>'
    return body


def generate_transcript_html(
    channel_name: str,
    customer_name: str,
    ticket_type: str,
    messages: list,
    guild: Optional[discord.Guild] = None,
) -> str:
    type_labels = {
        "schadensmeldung": "Schadensmeldung",
        "kundenkontakt": "Kundenkontakt",
    }
    type_label = type_labels.get(ticket_type, str(ticket_type).capitalize())
    msgs_html = ""
    prev_id = None
    shown = 0

    for msg in messages:
        ts = msg.created_at.astimezone(GERMANY_TZ).strftime("%d.%m.%Y %H:%M")
        edited = " <span class='edited'>(bearbeitet)</span>" if msg.edited_at else ""

        # Systemnachrichten (Anheften, Beitritte, …)
        if msg.type not in (discord.MessageType.default, discord.MessageType.reply):
            sys_text = getattr(msg, "system_content", "") or ""
            snap_only = bool(getattr(msg, "message_snapshots", None))
            if sys_text and not snap_only:
                msgs_html += f'<div class="sysmsg">{_esc(sys_text)} <span class="ts">{ts}</span></div>'
                shown += 1
                prev_id = None
                continue

        body = ""
        # Antwort-Vorschau
        ref = getattr(msg, "reference", None)
        resolved = getattr(ref, "resolved", None) if ref else None
        if (
            isinstance(resolved, discord.Message)
            and msg.type == discord.MessageType.reply
        ):
            snippet = (resolved.content or "Anhang / Embed")[:120]
            body += (
                f'<div class="reply">↪ <strong>{_esc(resolved.author.display_name)}</strong> '
                f"{_esc(snippet)}</div>"
            )
        body += _render_body_html(msg, guild)

        # Weitergeleitete Nachrichten
        for snap in getattr(msg, "message_snapshots", []) or []:
            snap_ts = (
                snap.created_at.astimezone(GERMANY_TZ).strftime("%d.%m.%Y %H:%M")
                if getattr(snap, "created_at", None)
                else ""
            )
            inner = (
                _render_body_html(snap, guild)
                or '<div class="msg-text"><em>(leer)</em></div>'
            )
            body += (
                f'<div class="fwd"><div class="fwd-label">↪ Weitergeleitet'
                f'{f" · {snap_ts}" if snap_ts else ""}</div>{inner}</div>'
            )
        if not body:
            body = '<div class="msg-text"><em>(keine Inhalte)</em></div>'

        is_cont = (
            prev_id == msg.author.id
            and not msg.embeds
            and not msg.components
            and not getattr(msg, "message_snapshots", None)
            and msg.type == discord.MessageType.default
        )
        prev_id = msg.author.id
        shown += 1

        av = (
            (str(msg.author.display_avatar.url).split("?")[0] + "?size=64")
            if msg.author.display_avatar
            else f"https://cdn.discordapp.com/embed/avatars/{msg.author.id % 6}.png"
        )
        uc = "#5865f2" if msg.author.bot else "#f2f3f5"

        if not is_cont:
            msgs_html += f"""
<div class="msg-group">
  <img class="avatar" src="{_esc(av)}" onerror="this.src='https://cdn.discordapp.com/embed/avatars/0.png'" loading="lazy">
  <div class="msg-body">
    <div class="msg-header">
      <span class="username" style="color:{uc}">{_esc(msg.author.display_name)}</span>
      {"<span class='bot-tag'>BOT</span>" if msg.author.bot else ""}
      <span class="ts">{ts}</span>{edited}
    </div>{body}
  </div>
</div>"""
        else:
            msgs_html += f'<div class="msg-cont">{body}</div>'

    css = """
* { box-sizing:border-box; margin:0; padding:0 }
body { background:#313338; color:#dcddde; font-family:"Helvetica Neue",Helvetica,Arial,sans-serif; font-size:15px; line-height:1.4 }
a { color:#00b0f4; text-decoration:none } a:hover { text-decoration:underline }
.header { background:#1e1f22; border-bottom:1px solid #232428; padding:14px 24px; display:flex; align-items:center; gap:12px; position:sticky; top:0; z-index:10 }
.ch-icon { font-size:22px; color:#80848e }
.ch-name { font-size:16px; font-weight:700; color:#f2f3f5 }
.badge { background:#5865f2; color:#fff; font-size:10px; font-weight:700; padding:2px 6px; border-radius:4px; margin-left:6px; letter-spacing:.3px }
.ch-meta { font-size:12px; color:#949ba4; margin-top:2px }
.messages { padding:20px 24px; max-width:860px; margin:0 auto }
.msg-group { display:flex; gap:12px; margin-top:14px; padding:2px 0 }
.msg-cont { padding:1px 0 1px 52px; margin-left:0 }
.avatar { width:40px; height:40px; border-radius:50%; flex-shrink:0; background:#36393f; object-fit:cover }
.msg-body { flex:1; min-width:0 }
.msg-header { display:flex; align-items:baseline; gap:8px; margin-bottom:2px }
.username { font-weight:600 }
.bot-tag { background:#5865f2; color:#fff; font-size:9px; font-weight:700; padding:1px 5px; border-radius:3px; text-transform:uppercase; letter-spacing:.3px }
.ts { color:#949ba4; font-size:11px } .edited { color:#949ba4; font-size:10px }
.msg-text, .cv-text, .embed-desc, .field-value { word-break:break-word }
.line { white-space:pre-wrap } .gap { height:8px }
.h1 { font-size:20px; font-weight:700; color:#fff; margin:4px 0 } .h2 { font-size:18px; font-weight:700; color:#fff; margin:4px 0 } .h3 { font-size:16px; font-weight:700; color:#fff; margin:3px 0 }
.sub { font-size:12px; color:#949ba4 }
.quote { border-left:3px solid #4e5058; padding-left:10px; margin:1px 0 }
.mention { background:rgba(88,101,242,.3); color:#c9cdfb; border-radius:3px; padding:0 2px }
code { background:#1e1f22; border-radius:3px; padding:1px 4px; font-size:13px }
pre.code { background:#1e1f22; border:1px solid #232428; border-radius:4px; padding:8px 10px; margin:4px 0; white-space:pre-wrap; font-size:13px }
.emoji { width:20px; height:20px; vertical-align:-4px }
.attachment { color:#00b0f4; font-size:13px; margin-top:3px }
.embed { background:#2b2d31; border-radius:0 4px 4px 0; padding:12px 16px; margin-top:4px; max-width:560px }
.embed-author { color:#dcddde; font-size:13px; font-weight:600; margin-bottom:4px }
.embed-title { color:#fff; font-weight:600; margin-bottom:4px }
.embed-title-link { color:#00b0f4; font-weight:600; display:block; margin-bottom:4px }
.embed-desc { color:#dcddde; font-size:14px; margin-bottom:6px }
.embed-img, .thumb { max-width:100%; max-height:320px; border-radius:4px; margin-top:6px }
.cv-text { font-size:14px; margin:2px 0 } .sep { border:0; border-top:1px solid #3f4147; margin:8px 0 }
.cv-section { display:flex; justify-content:space-between; gap:12px } .thumb { max-width:80px; max-height:80px }
.row { display:flex; flex-wrap:wrap; gap:6px; margin-top:6px }
.btn { background:#4e5058; color:#fff; font-size:13px; font-weight:600; padding:4px 12px; border-radius:4px } .btn.off { opacity:.5 }
.field-row { display:flex; flex-wrap:wrap; gap:12px; margin-top:6px }
.field-block, .field-block--inline { margin-top:6px }
.field-block--inline { flex:1; min-width:120px }
.field-name { color:#fff; font-weight:600; font-size:13px; margin-bottom:2px }
.field-value { color:#dcddde; font-size:14px }
.embed-footer { color:#949ba4; font-size:12px; margin-top:8px; padding-top:8px; border-top:1px solid #3f4147 }
.reply { color:#949ba4; font-size:13px; border-left:2px solid #4e5058; padding-left:8px; margin-bottom:3px }
.fwd { border-left:3px solid #4e5058; padding:2px 0 2px 10px; margin-top:4px }
.fwd-label { color:#949ba4; font-size:12px; margin-bottom:2px }
.sysmsg { color:#949ba4; font-size:13px; text-align:center; margin-top:12px }
.footer { text-align:center; color:#4e5058; font-size:12px; padding:24px; margin-top:32px; border-top:1px solid #232428 }
"""

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Transcript — {_esc(channel_name)}</title>
<style>{css}</style>
</head>
<body>
<div class="header">
  <span class="ch-icon">#</span>
  <div>
    <div class="ch-name">{_esc(channel_name)}<span class="badge">{_esc(type_label)}</span></div>
    <div class="ch-meta">Kunde: {_esc(customer_name)} &nbsp;·&nbsp; {shown} Nachrichten &nbsp;·&nbsp; Export {get_now().strftime("%d.%m.%Y, %H:%M Uhr")}</div>
  </div>
</div>
<div class="messages">{msgs_html}</div>
<div class="footer">Deutsche Versicherungsgesellschaft &nbsp;·&nbsp; Ticket-Transcript</div>
</body>
</html>"""


def build_transcript_bytes(
    channel: discord.TextChannel, ticket_info: dict, messages: list
) -> Optional[bytes]:
    """Erzeugt das Transcript als HTML (UTF-8). Gibt None zurück, wenn es fehlschlägt."""
    try:
        customer_id = ticket_info.get("customer_id", "")
        customer = data["customers"].get(customer_id, {})
        customer_name = customer.get("rp_name", customer_id or "Unbekannt")
        html_content = generate_transcript_html(
            channel.name,
            customer_name,
            ticket_info.get("type", ""),
            messages,
            channel.guild,
        )
        return html_content.encode("utf-8")
    except Exception as e:
        logger.error(f"Transcript Generierungsfehler: {e}", exc_info=True)
        return None


def transcript_file(channel_name: str, raw: bytes) -> discord.File:
    return discord.File(io.BytesIO(raw), filename=f"transcript-{channel_name}.html")


# ═══════════════════════════════════════════════════════
#   TICKET CLOSE HELPER (DRY — inkl. Transcript)
# ═══════════════════════════════════════════════════════
async def close_ticket_channel(
    interaction: Optional[discord.Interaction],
    channel: discord.TextChannel,
    ticket_info: dict,
    auto_close: bool = False,
) -> None:
    closer_mention = interaction.user.mention if interaction else "System System"
    closer_id = getattr(interaction.user, "id", 0) if interaction else 0

    if interaction and not interaction.response.is_done():
        await interaction.response.defer()

    # ── Alle Nachrichten + Transcript (HTML-Datei) ───────────────────────────
    messages = [msg async for msg in channel.history(limit=None, oldest_first=True)]
    transcript_raw = build_transcript_bytes(channel, ticket_info, messages)

    # ── Bearbeitungszeit berechnen ───────────────────────────────────────────
    customer_id = ticket_info.get("customer_id", "")
    ticket_type = ticket_info.get("type", "")
    opened_at_str = ticket_info.get("opened_at")
    claimed_by = ticket_info.get("claimed_by")
    claimed_at = ticket_info.get("claimed_at")
    duration_min = None

    if opened_at_str:
        try:
            opened_dt = make_aware(datetime.fromisoformat(opened_at_str))
            duration_min = max(1, int((get_now() - opened_dt).total_seconds() / 60))
            data.setdefault("ticket_stats", []).append(
                {
                    "type": ticket_type,
                    "customer_id": customer_id,
                    "channel_name": channel.name,
                    "opened_at": opened_at_str,
                    "claimed_at": claimed_at,
                    "claimed_by": claimed_by,
                    "closed_at": get_now().isoformat(),
                    "closed_by": closer_id,
                    "duration_minutes": duration_min,
                    "auto_close": auto_close,
                }
            )
        except Exception as ex:
            logger.error(f"Ticket-Stats Fehler: {ex}")

    # ── Schadenhistorie aktualisieren ────────────────────────────────────────
    if ticket_type == "schadensmeldung" and customer_id in data.get(
        "schaden_historie", {}
    ):
        for entry in data["schaden_historie"][customer_id]:
            if entry.get("kanal_id") == channel.id and entry.get("status") == "offen":
                entry["status"] = "abgeschlossen"
                entry["closed_at"] = get_now().isoformat()
                entry["closed_by"] = closer_id
                break
        # Panel-Bearbeitungszeit direkt nach Abschluss aktualisieren
        asyncio.create_task(_do_panel_refresh())

    log_channel = (
        channel.guild.get_channel(config["log_channel_id"])
        if config.get("log_channel_id")
        else None
    )
    # Ohne Log-Kanal wird das Transcript an die Abschlussnachricht gehängt
    transcript_in_close_msg = bool(transcript_raw) and log_channel is None

    # ── Abschlussnachricht im Ticket ─────────────────────────────────────────
    title_text = (
        "Ticket automatisch geschlossen!" if auto_close else "Ticket geschlossen!"
    )
    desc_parts = [
        (
            "**Bearbeitung abgeschlossen.**"
            if not auto_close
            else "**Wegen Inaktivität automatisch geschlossen.**"
        )
    ]
    if not auto_close:
        desc_parts.append("Kanal wird in **5 Sekunden** gelöscht.")
    if duration_min:
        h, m = divmod(duration_min, 60)
        desc_parts.append(f"<:datetime:1522597873286512777> `{h}h {m}min`")

    close_embed = dvg_embed(title_text, "\n".join(p for p in desc_parts if p))
    if not auto_close:
        close_embed.add_field(
            name="Geschlossen von",
            value=f"<:archiviert:1522597781557219448> {closer_mention}",
            inline=False,
        )
    if transcript_raw:
        close_embed.add_field(
            name="Transcript",
            value=(
                "Als HTML-Datei angehängt."
                if transcript_in_close_msg
                else "Als HTML-Datei im Log-Kanal abgelegt."
            ),
            inline=False,
        )
    else:
        close_embed.add_field(
            name="Transcript",
            value="Konnte nicht erstellt werden.",
            inline=False,
        )

    close_kwargs = {}
    if transcript_in_close_msg:
        tf = transcript_file(channel.name, transcript_raw)
        close_kwargs = {**ev(close_embed, file=tf.filename), "file": tf}
    else:
        close_kwargs = ev(close_embed)

    if interaction and interaction.response.is_done():
        await interaction.followup.send(**close_kwargs)
    else:
        await channel.send(**close_kwargs)

    # ── Log-Kanal ────────────────────────────────────────────────────────────
    log_e = dvg_embed(
        f"Ticket geschlossen{'  –  Inaktivität' if auto_close else ''}",
        "Dieses Ticket wurde erfolgreich geschlossen. Die zugehörigen Details sind nachfolgend aufgeführt.",
    )
    log_e.add_field(
        name="Kanal",
        value=f"<:channel:1522597774095286313> `{channel.name}`",
        inline=False,
    )
    log_e.add_field(
        name="Kunden-ID",
        value=f"<:id:1522597735205830666> `{customer_id}`",
        inline=False,
    )
    log_e.add_field(
        name="Geschlossen von",
        value=f"<:archiviert:1522597781557219448> {closer_mention}",
        inline=True,
    )
    if duration_min:
        h, m = divmod(duration_min, 60)
        log_e.add_field(
            name="Bearbeitungsdauer",
            value=f"<:datetime:1522597873286512777> `{h}h {m}min`",
            inline=True,
        )
    log_file = (
        transcript_file(channel.name, transcript_raw)
        if (transcript_raw and log_channel is not None)
        else None
    )
    await send_to_log_channel(channel.guild, log_e, file=log_file)

    # ── Daten bereinigen ─────────────────────────────────────────────────────
    ch_key = str(channel.id)
    if ch_key in data.get("ticket_channels", {}):
        del data["ticket_channels"][ch_key]
    save_data(data)

    add_log_entry(
        "TICKET_GESCHLOSSEN",
        closer_id,
        {
            "customer_id": customer_id,
            "channel_name": channel.name,
            "auto_close": auto_close,
            "transcript": "HTML-Datei" if transcript_raw else "—",
            "nachrichten": len(messages),
        },
    )

    await asyncio.sleep(5)
    try:
        await channel.delete(reason="Ticket geschlossen")
    except discord.NotFound:
        pass


# ═══════════════════════════════════════════════════════
#   INAKTIVITÄTS-SYSTEM — HELPERS
# ═══════════════════════════════════════════════════════
async def _send_inactivity_warning(
    channel: discord.TextChannel, ch_id_str: str, ticket_info: dict
) -> None:
    """Sendet die 16h-Inaktivitätswarnung mit Cancel-Button."""
    guild = channel.guild
    claimed_by = ticket_info.get("claimed_by")
    opener_id = ticket_info.get("opener_id")
    customer = data["customers"].get(ticket_info.get("customer_id", ""), {})
    cust_user = guild.get_member(customer.get("discord_user_id", 0))

    # Wer wird gepingt: Claimer (falls vorhanden) oder Opener + Kunde
    pings: List[str] = []
    if claimed_by and (claimer := guild.get_member(claimed_by)):
        pings.append(claimer.mention)
    elif opener_id and (opener := guild.get_member(opener_id)):
        pings.append(opener.mention)
    if cust_user:
        pings.append(cust_user.mention)

    auto_close_time = get_now() + timedelta(hours=8)
    warn_embed = DEmbed(
        title="Inaktivitätswarnung",
        description=(
            "> Dieses Ticket ist seit **16 Stunden** inaktiv.\n"
            "> Es wird **automatisch geschlossen**, wenn keine Reaktion erfolgt.\n"
            "> Klicke auf den Button, um das automatische Schließen abzubrechen."
        ),
        color=EMBED_COLOR,
        timestamp=get_now(),
    )
    warn_embed.add_field(
        name="Automatisches Schließen um",
        value=f"> `{auto_close_time.strftime('%d.%m.%Y, %H:%M Uhr')}`",
        inline=False,
    )

    await channel.send(
        **ev(
            warn_embed,
            view=InaktivitätsWarnView(),
            ping=" ".join(pings) if pings else None,
        )
    )

    data["ticket_channels"][ch_id_str]["inactivity_warned_at"] = get_now().isoformat()
    save_data(data)
    logger.info(f"Inaktivitätswarnung gesendet: #{channel.name}")


async def _auto_close_ticket(
    guild: discord.Guild, ch_id_str: str, ticket_info: dict
) -> None:
    """Schließt ein Ticket automatisch wegen Inaktivität."""
    channel = guild.get_channel(int(ch_id_str))
    if not channel:
        data["ticket_channels"].pop(ch_id_str, None)
        save_data(data)
        return
    logger.info(f"Auto-Close: #{channel.name} (Inaktivität)")
    await close_ticket_channel(None, channel, ticket_info, auto_close=True)


def add_log_entry(action: str, user_id: int, details: dict):
    data["logs"].append(
        {
            "timestamp": get_now().isoformat(),
            "action": action,
            "user_id": user_id,
            "details": details,
        }
    )
    save_data(data)


def get_verfügbares_guthaben(customer_id: str, versicherung: str) -> float:
    limit = get_insurance_types().get(versicherung, {}).get("auszahlung_limit", 0.0)
    ausgezahlt = (
        data["customers"]
        .get(customer_id, {})
        .get("auszahlungen", {})
        .get(versicherung, 0.0)
    )
    return max(0.0, limit - ausgezahlt)


def create_zip_buffer() -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if os.path.exists(DATA_FILE):
            zf.write(DATA_FILE, arcname="insurance_data.json")
        if os.path.exists(CONFIG_FILE):
            zf.write(CONFIG_FILE, arcname="bot_config.json")
    buf.seek(0)
    return buf


def customer_has_unpaid_invoice(customer_id: str) -> Optional[str]:
    """Gibt die erste offene Rechnungs-ID zurück, oder None."""
    for inv_id, inv in data["invoices"].items():
        if inv["customer_id"] == customer_id and not inv.get("paid", False):
            return inv_id
    return None


def get_active_ticket(user_id: int, ticket_type: str) -> Optional[int]:
    """Gibt channel_id zurück, wenn der User ein aktives Ticket dieses Typs hat."""
    for ch_id, info in data.get("ticket_channels", {}).items():
        if info.get("type") == ticket_type and info.get("opener_id") == user_id:
            return int(ch_id)
    return None


def customer_has_active_ticket(customer_id: str, ticket_type: str) -> Optional[int]:
    """Prüft, ob für einen Kunden bereits ein aktives Ticket dieses Typs existiert."""
    for ch_id, info in data.get("ticket_channels", {}).items():
        if info.get("type") == ticket_type and info.get("customer_id") == customer_id:
            return int(ch_id)
    return None


def check_nachweis_duplicate(nachweis: str) -> Optional[dict]:
    """
    Prüft ob ein Schadennachweis (Link / Rechnungsnr.) bereits eingereicht wurde.
    Gibt den Historieneintrag zurück, wenn ein Duplikat gefunden wird.
    """
    clean = nachweis.strip().lower()
    if not clean:
        return None
    for cid, history in data.get("schaden_historie", {}).items():
        for entry in history:
            if entry.get("nachweis", "").strip().lower() == clean:
                return {**entry, "customer_id": cid}
    return None


def get_paid_invoice_count(customer_id: str) -> int:
    """Anzahl der bezahlten Rechnungen eines Kunden (= Anzahl Monatsbeiträge)."""
    return sum(
        1
        for inv in data["invoices"].values()
        if inv.get("customer_id") == customer_id and inv.get("paid", False)
    )


def can_cancel_insurance(customer_id: str) -> Tuple[bool, int]:
    """
    Mindestlaufzeit: 4 bezahlte Rechnungen (4 Monatsbeiträge).
    Returns (kündigung_erlaubt, anzahl_bezahlter_rechnungen).
    """
    paid = get_paid_invoice_count(customer_id)
    return paid >= 4, paid


# ── Autocomplete-Funktionen ──────────────────────────────────────────────────
async def customer_id_autocomplete(
    interaction: discord.Interaction, current: str
) -> List[app_commands.Choice[str]]:
    """Autocomplete für aktive Kunden-IDs (RP-Name + ID als Anzeige)."""
    q = current.lower().strip()
    choices = []
    for cid, c in data["customers"].items():
        if c.get("status") == "archiviert":
            continue
        rp = c.get("rp_name", "")
        if not q or q in cid.lower() or q in rp.lower():
            choices.append(app_commands.Choice(name=f"{rp}  ({cid})"[:100], value=cid))
        if len(choices) >= 25:
            break
    return choices


async def customer_id_all_autocomplete(
    interaction: discord.Interaction, current: str
) -> List[app_commands.Choice[str]]:
    """Autocomplete für alle Kunden-IDs (inkl. archivierte)."""
    q = current.lower().strip()
    choices = []
    for cid, c in data["customers"].items():
        rp = c.get("rp_name", "")
        status = "Archiviert" if c.get("status") == "archiviert" else "Aktiv"
        if not q or q in cid.lower() or q in rp.lower():
            choices.append(
                app_commands.Choice(name=f"[{status}] {rp}  ({cid})"[:100], value=cid)
            )
        if len(choices) >= 25:
            break
    return choices


async def invoice_id_autocomplete(
    interaction: discord.Interaction, current: str
) -> List[app_commands.Choice[str]]:
    """Autocomplete für Rechnungs-IDs."""
    q = current.lower().strip()
    choices = []
    for inv_id, inv in data["invoices"].items():
        if not q or q in inv_id.lower():
            cust = data["customers"].get(inv.get("customer_id", ""), {})
            status = "bezahlt" if inv.get("paid") else "offen"
            label = f"{inv_id}  —  {cust.get('rp_name', '?')}  ({status}, {inv.get('betrag', 0):,.0f} EUR)"
            choices.append(app_commands.Choice(name=label[:100], value=inv_id))
        if len(choices) >= 25:
            break
    return choices


# ── Blacklist-Helfer ──────────────────────────────────────────────────────────
def is_blacklisted(customer_id: str) -> bool:
    return customer_id in data.get("blacklist", {})


def blacklist_entry(customer_id: str) -> Optional[dict]:
    return data.get("blacklist", {}).get(customer_id)


# ── DM-Erinnerungs-Helfer ────────────────────────────────────────────────────
async def send_invoice_due_dm(guild: discord.Guild, invoice_id: str, inv: dict):
    """Sendet dem Kunden eine DM 24h vor Rechnungsfälligkeit."""
    customer = data["customers"].get(inv.get("customer_id", ""))
    if not customer:
        return
    member = guild.get_member(customer.get("discord_user_id", 0))
    if not member:
        return
    due = make_aware(datetime.fromisoformat(inv["due_date"])).strftime("%d.%m.%Y")
    dm = dvg_embed(
        "Zahlungserinnerung",
        f"> Ihre Versicherungsrechnung ist in **24 Stunden** fällig.\n"
        f"> Bitte begleichen Sie den Betrag rechtzeitig, um eine Mahnung zu vermeiden.",
    )
    dm.add_field(name="Rechnungsnummer", value=f"> `{invoice_id}`", inline=True)
    dm.add_field(
        name="Betrag", value=f"> `{inv.get('betrag', 0):,.2f} EUR`", inline=True
    )
    dm.add_field(name="Fällig am", value=f"> `{due}`", inline=True)
    dm.add_field(
        name="Zahlungsmethode",
        value=f"> HBpay: `{customer.get('hbpay_nummer', '—')}`",
        inline=False,
    )
    try:
        await member.send(**ev(dm))
        data["invoices"][invoice_id]["dm_reminder_sent"] = True
        save_data(data)
        logger.info(f"Zahlungserinnerung per DM gesendet: {invoice_id} -> {member}")
    except discord.Forbidden:
        logger.warning(f"DM für {invoice_id} gesperrt ({member})")


# ═══════════════════════════════════════════════════════
#   BERECHTIGUNGSPRÜFUNGEN  (Bugfix: Tuple-Role-IDs)
# ═══════════════════════════════════════════════════════
def _has_any_role(interaction: discord.Interaction, role_ids) -> bool:
    """Prüft, ob der User mindestens eine der angegebenen Rollen hat (auch als Tuple)."""
    if not isinstance(role_ids, tuple):
        role_ids = (role_ids,)
    return any(
        (role := interaction.guild.get_role(rid)) is not None
        and role in interaction.user.roles
        for rid in role_ids
    )


def _get_roles(guild: discord.Guild, role_ids) -> List[discord.Role]:
    """Gibt alle gefundenen Rollen zurück."""
    if not isinstance(role_ids, tuple):
        role_ids = (role_ids,)
    return [r for rid in role_ids if (r := guild.get_role(rid)) is not None]


def is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.id in ADMIN_USER_IDS


def is_mitarbeiter(interaction: discord.Interaction) -> bool:
    return (
        _has_any_role(interaction, MITARBEITER_ROLE_ID)
        or _has_any_role(interaction, LEITUNGSEBENE_ROLE_ID)
        or is_admin(interaction)
    )


def is_leitungsebene(interaction: discord.Interaction) -> bool:
    return _has_any_role(interaction, LEITUNGSEBENE_ROLE_ID) or is_admin(interaction)


def is_firmenkontorolle(interaction: discord.Interaction) -> bool:
    return _has_any_role(interaction, FIRMENKONTOROLLE_ROLE_ID) or is_admin(interaction)


def build_error_embed(
    title: str, description: str, needed_permission: Optional[str] = None
) -> discord.Embed:
    e = dvg_embed(title, description)
    e.color = discord.Color(COLOR_ERROR)  # roter Container ohne Fußzeile
    e.timestamp = None
    if needed_permission:
        e.add_field(
            name="Erforderliche Berechtigung",
            value=f"> `{needed_permission}`",
            inline=False,
        )
    return e


# ═══════════════════════════════════════════════════════
#   KUNDENAKTE EMBED & THREAD HELPERS
# ═══════════════════════════════════════════════════════
def build_kundenakte_embed(customer_id: str, customer: dict) -> discord.Embed:
    ins_types = get_insurance_types()
    total_price = customer.get("total_monthly_price", 0.0)
    embed = dvg_embed("Versicherungsakte", big=True)
    embed.add_field(
        name="Versicherungsnehmer",
        value=f"> <:member:1522597880437932112> `{customer['rp_name']}`\n> <:id:1522597735205830666> `{customer_id}`",
        inline=False,
    )
    embed.add_field(
        name="Zahlungsmethode",
        value=f"> <:hbpay:1522597775647178905> `{customer['hbpay_nummer']}`",
        inline=False,
    )
    ins_text = "\n".join(
        f"> {ins}\n> ▸ `{ins_types.get(ins, {}).get('price', 0.0):,.2f}€/Monat`"
        for ins in customer.get("versicherungen", [])
    )
    embed.add_field(
        name="Abgeschlossene Versicherungen",
        value=ins_text or "> *Keine Versicherungen abgeschlossen!*",
        inline=False,
    )
    embed.add_field(
        name="Gesamtbeitrag (monatlich)",
        value=f"> <:einzahlung:1522597871051079710> `{total_price:,.2f}€/Monat` zzgl. 19% Steuern",
        inline=False,
    )
    return embed


async def update_forum_thread_embed(
    guild: discord.Guild, customer_id: str, customer: dict
):
    thread_id = customer.get("thread_id")
    if not thread_id:
        return
    try:
        thread = guild.get_thread(thread_id)
        if not thread:
            thread = await guild.fetch_channel(thread_id)
        async for msg in thread.history(limit=5, oldest_first=True):
            if msg.author.id == (guild.me.id if guild.me else bot.user.id) and (
                msg.embeds or msg.flags.components_v2
            ):
                uid = customer.get("discord_user_id")
                ping = f"<@{uid}>" if uid else ""
                await msg.edit(
                    **v2_edit(
                        msg, build_kundenakte_embed(customer_id, customer), ping=ping
                    )
                )
                return
    except Exception as e:
        logger.error(f"Forum-Thread Update Fehler: {e}")


async def update_customer_thread_backup(guild: discord.Guild, customer_id: str):
    customer = data["customers"].get(customer_id)
    if not customer:
        return
    thread_id = customer.get("thread_id")
    if not thread_id:
        return
    try:
        thread = guild.get_thread(thread_id)
        if not thread:
            thread = await guild.fetch_channel(thread_id)
        if not thread:
            return

        old_id = customer.get("backup_message_id")
        if old_id:
            try:
                old_msg = await thread.fetch_message(old_id)
                await old_msg.delete()
            except Exception:
                pass

        backup_data = {
            "customer_id": customer_id,
            "exported_at": get_now().isoformat(),
            "customer": customer,
        }
        buf = io.BytesIO(
            json.dumps(backup_data, indent=2, ensure_ascii=False).encode("utf-8")
        )
        buf.seek(0)
        file = discord.File(buf, filename=f"akte_{customer_id}.json")

        embed = DEmbed(
            title="Aktuelle Kundendaten",
            description=f"> Diese Datei enthält den aktuellen Datenstand der Akte `{customer_id}`.\n> Sie wird bei jeder Änderung automatisch aktualisiert.",
            color=EMBED_COLOR,
            timestamp=get_now(),
        )
        embed.add_field(
            name="Kunde", value=f"> `{customer.get('rp_name', '—')}`", inline=True
        )
        embed.add_field(
            name="Stand",
            value=f"> {get_now().strftime('%d.%m.%Y, %H:%M Uhr')}",
            inline=True,
        )

        msg = await thread.send(file=file, **ev(embed, file=file.filename))
        data["customers"][customer_id]["backup_message_id"] = msg.id
        save_data(data)
    except Exception as e:
        logger.error(f"Kunden-Thread Backup Fehler ({customer_id}): {e}", exc_info=True)


# ═══════════════════════════════════════════════════════
#   MODUL-SYSTEM
# ═══════════════════════════════════════════════════════
IMMER_SICHTBAR = {"server", "ping", "backup", "reload", "panel-aktualisieren"}

MODUL_COMMANDS = {
    "versicherung": {
        "kunden-suchen",
        "versicherung-kuendigen",
        "rechnungen-uebersicht",
        "einstellung-steuer",
        "einstellung-versicherung-neu",
        "einstellung-versicherung-edit",
        "einstellung-versicherungen-liste",
        "einstellung-kanaele",
        "kundenakte-erstellen",
        "versicherung-hinzubuchen",
        "rechnung-ausstellen",
        "rechnung-archivieren",
        "mahnung-ausstellen",
        "akte-archivieren",
        "auszahlung-einreichen",
        "akte-anzeigen",
        "statistiken",
        "logs-anzeigen",
        "add",
        "remove",
        "schaden-historie",
        "blacklist-add",
        "blacklist-remove",
        "blacklist-liste",
    },
}

_CMD_CACHE: Dict[str, object] = {}


def get_aktive_module(guild_id: int) -> set:
    return set(config.get("guild_modules", {}).get(str(guild_id), []))


def set_modul_config(guild_id: int, modul: str, aktiv: bool):
    if "guild_modules" not in config:
        config["guild_modules"] = {}
    key = str(guild_id)
    lst = list(config["guild_modules"].get(key, []))
    if aktiv and modul not in lst:
        lst.append(modul)
    elif not aktiv and modul in lst:
        lst.remove(modul)
    config["guild_modules"][key] = lst
    save_config(config)


def _restore_globals():
    for name, cmd in _CMD_CACHE.items():
        try:
            bot.tree.add_command(cmd, override=True)
        except Exception:
            pass


async def guild_sync(guild: discord.Guild, aktive_module: set) -> list:
    guild_obj = discord.Object(id=guild.id)
    erlaubt = set(IMMER_SICHTBAR)
    for m in aktive_module:
        erlaubt |= MODUL_COMMANDS.get(m, set())

    _restore_globals()
    bot.tree.copy_global_to(guild=guild_obj)
    for cmd in bot.tree.get_commands(guild=guild_obj):
        if cmd.name not in erlaubt:
            bot.tree.remove_command(cmd.name, guild=guild_obj)
    try:
        synced = await bot.tree.sync(guild=guild_obj)
        logger.info(f"Guild '{guild.name}': {len(synced)} Commands für {aktive_module}")
    except Exception as ex:
        logger.error(f"Guild-Sync Fehler ({guild.id}): {ex}")
        synced = []

    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()
    return synced


# ═══════════════════════════════════════════════════════
#   ON READY
# ═══════════════════════════════════════════════════════
@bot.event
async def on_ready():
    global _CMD_CACHE
    logger.info(f"{bot.user} ist online ({bot.user.id})")
    _CMD_CACHE = {cmd.name: cmd for cmd in bot.tree.get_commands()}
    logger.info(f"on_ready: {len(_CMD_CACHE)} Commands gecacht")
    for guild in bot.guilds:
        aktive = get_aktive_module(guild.id)
        await guild_sync(guild, aktive)

    # Persistent Views registrieren
    register_persistent(KundenkontaktView())
    register_persistent(SchadensmeldungView())
    register_persistent(TicketCloseView(0, ""))  # Legacy-Compat für bestehende Tickets
    register_persistent(SchadensmeldungTicketView())  # Neue Schadensmeldungs-Tickets
    register_persistent(KundenkontaktTicketView())  # Neue Kundenkontakt-Tickets
    register_persistent(
        CloseRequestView()
    )  # Schließanfrage: Annehmen/Ablehnen durch den Kunden
    register_persistent(InaktivitätsWarnView())  # Inaktivitätswarnung
    register_persistent(AuszahlungActionView("dummy", "dummy", 0.0))

    # Verwaiste ticket_channels-Einträge bereinigen (Channel bereits gelöscht)
    stale_keys = []
    for ch_id_str in list(data.get("ticket_channels", {}).keys()):
        found = False
        for guild in bot.guilds:
            if guild.get_channel(int(ch_id_str)):
                found = True
                break
        if not found:
            stale_keys.append(ch_id_str)
    if stale_keys:
        for k in stale_keys:
            data["ticket_channels"].pop(k, None)
        save_data(data)
        logger.info(f"Bereinigte {len(stale_keys)} verwaiste Ticket-Einträge.")

    await asyncio.sleep(1)
    if not check_invoices.is_running():
        check_invoices.start()
    if not auto_backup.is_running():
        auto_backup.start()
    if not check_ticket_inactivity.is_running():
        check_ticket_inactivity.start()
    if not refresh_schadensmeldung_panel.is_running():
        refresh_schadensmeldung_panel.start()

    # Panel einmalig beim Start aktualisieren (bestehende Daten sofort anwenden)
    await asyncio.sleep(2)
    await _do_panel_refresh()


@bot.event
async def on_guild_join(guild: discord.Guild):
    await guild_sync(guild, set())


# ═══════════════════════════════════════════════════════
#   PING
# ═══════════════════════════════════════════════════════
@bot.tree.command(
    name="ping", description="Zeigt den Status und die Latenz des Bots an"
)
async def ping(interaction: discord.Interaction):
    ms = round(bot.latency * 1000)
    customers = data.get("customers", {})
    aktive = sum(1 for c in customers.values() if c.get("status") == "aktiv")
    archiviert = sum(1 for c in customers.values() if c.get("status") == "archiviert")
    off_re = sum(1 for inv in data.get("invoices", {}).values() if not inv.get("paid"))
    aus_pend = sum(
        1
        for az in data.get("pending_auszahlungen", {}).values()
        if az.get("status") == "ausstehend"
    )
    offene_tk = len(data.get("ticket_channels", {}))

    color = COLOR_SUCCESS if ms < 100 else (COLOR_WARNING if ms < 200 else COLOR_ERROR)
    status_val = (
        f"> **`{ms} ms`** — Ausgezeichnete Verbindung!"
        if ms < 100
        else (
            f"> **`{ms} ms`** — Stabile Verbindung!"
            if ms < 200
            else f"> **`{ms} ms`** — Schlechte Verbindung!"
        )
    )
    embed = DEmbed(
        title="Systemstatus InsuranceGuard v4", color=color, timestamp=get_now()
    )
    embed.add_field(name="Verbindung", value=status_val, inline=False)
    embed.add_field(
        name="Offene Vorgänge",
        value=f"> `-` **`{off_re}`** Rechnungen\n> `-` **`{aus_pend}`** Auszahlungen\n> `-` **`{offene_tk}`** Tickets",
        inline=True,
    )
    embed.add_field(
        name="Serverzeit",
        value=f"> {get_now().strftime('%d.%m.%Y, %H:%M Uhr')}",
        inline=False,
    )
    await interaction.response.send_message(ephemeral=True, **ev(embed))


# ═══════════════════════════════════════════════════════
#   /modul
# ═══════════════════════════════════════════════════════
@bot.tree.command(
    name="server", description="[ADMIN] Versicherungsmodul aktivieren oder deaktivieren"
)
@app_commands.describe(aktion="Modul aktivieren oder deaktivieren")
@app_commands.choices(
    aktion=[
        app_commands.Choice(name="Aktivieren", value="aktivieren"),
        app_commands.Choice(name="Deaktivieren", value="deaktivieren"),
    ]
)
async def modul_cmd(interaction: discord.Interaction, aktion: str):
    if not is_admin(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!",
                    "Nur Administratoren können Module verwalten.",
                    "Administrator",
                )
            ),
        )
        return
    await interaction.response.defer(ephemeral=True)
    aktiv = aktion == "aktivieren"
    set_modul_config(interaction.guild_id, "versicherung", aktiv)
    aktive = get_aktive_module(interaction.guild_id)
    synced = await guild_sync(interaction.guild, aktive)
    icon = "" if aktiv else ""
    e = DEmbed(
        title="Modul aktiviert!" if aktiv else "Modul deaktiviert!",
        description=(
            f"> **Versicherungsfirma** wurde {'aktiviert' if aktiv else 'deaktiviert'}!\n"
            f"> <:commands:1522597835839639683> **`{len(synced)}`** Befehle synchronisiert"
        ),
        color=EMBED_COLOR if aktiv else COLOR_WARNING,
        timestamp=get_now(),
    )
    e.add_field(
        name="Aktuelle Module", value=f"> {icon} Versicherungsfirma", inline=False
    )
    e.add_field(
        name="Hinweis",
        value="> Sollten die Befehle nicht sofort erscheinen, lade die Discord-App neu.",
        inline=False,
    )
    await interaction.followup.send(ephemeral=True, **ev(e))
    add_log_entry(
        "MODUL_GEAENDERT",
        interaction.user.id,
        {"modul": "versicherung", "aktion": aktion},
    )


# ═══════════════════════════════════════════════════════
#   BACKUP & RELOAD
# ═══════════════════════════════════════════════════════
@bot.tree.command(
    name="backup", description="Erstellt ein Backup und sendet es als ZIP"
)
async def backup_download(interaction: discord.Interaction):
    if not is_leitungsebene(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!",
                    "Nur die Leitungsebene kann Backups herunterladen.",
                    "Leitungsebene",
                )
            ),
        )
        return
    await interaction.response.defer(ephemeral=True)
    try:
        create_backup()
        buf = create_zip_buffer()
        file = discord.File(
            buf, filename=f"insurance_backup_{get_now().strftime('%Y%m%d_%H%M%S')}.zip"
        )
        await interaction.followup.send(
            file=file,
            ephemeral=True,
            **ev(
                dvg_embed(
                    "Vollständiger Datenbank-Export",
                    "Das Backup wurde als ZIP-Datei angehängt.",
                ),
                file=file.filename,
            ),
        )
    except Exception as e:
        await interaction.followup.send(ephemeral=True, **ev_text(f" Fehler: {e}"))


@bot.tree.command(
    name="reload", description="Stellt eine Datenbank-Datei (JSON) wieder her"
)
@app_commands.describe(datei="insurance_data.json oder bot_config.json")
async def reload_backup(interaction: discord.Interaction, datei: discord.Attachment):
    if not is_leitungsebene(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!",
                    "Nur die Leitungsebene kann Backups wiederherstellen.",
                    "Leitungsebene",
                )
            ),
        )
        return
    if not datei.filename.endswith(".json"):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Falscher Dateityp!", "Nur `.json` Dateien sind erlaubt."
                )
            ),
        )
        return
    await interaction.response.defer(ephemeral=True)
    try:
        create_backup()
        content = await datei.read()
        json_obj = json.loads(content.decode("utf-8"))
        if "customers" in json_obj and "logs" in json_obj:
            global data
            data = json_obj
            for key in ("schadensmeldungen", "pending_auszahlungen", "ticket_channels"):
                if key not in data:
                    data[key] = {}
            save_data(data)
            await interaction.followup.send(
                ephemeral=True, **ev_text(" `insurance_data.json` wiederhergestellt.")
            )
        elif "log_channel_id" in json_obj or "insurance_types" in json_obj:
            global config
            config = json_obj
            save_config(config)
            await interaction.followup.send(
                ephemeral=True, **ev_text(" `bot_config.json` wiederhergestellt.")
            )
        else:
            await interaction.followup.send(
                ephemeral=True, **ev_text(" Unbekanntes Dateiformat.")
            )
    except Exception as e:
        await interaction.followup.send(ephemeral=True, **ev_text(f" Fehler: {e}"))


# ═══════════════════════════════════════════════════════
#   KUNDEN-SUCHE
# ═══════════════════════════════════════════════════════
@bot.tree.command(
    name="kunden-suchen",
    description="Sucht nach Kunden anhand des RP-Namens oder der Kunden-ID",
)
@app_commands.describe(suchbegriff="RP-Name, Kunden-ID oder Kartennummer")
async def kunden_suchen(interaction: discord.Interaction, suchbegriff: str):
    if not is_mitarbeiter(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!",
                    "Nur Mitarbeiter können die Kundensuche verwenden.",
                    "Mitarbeiter",
                )
            ),
        )
        return
    await interaction.response.defer(ephemeral=True)
    try:
        q = suchbegriff.lower().strip()
        treffer = [
            (cid, c)
            for cid, c in data["customers"].items()
            if q in cid.lower()
            or q in c.get("rp_name", "").lower()
            or q in c.get("hbpay_nummer", "").lower()
        ]
        if not treffer:
            embed = DEmbed(
                title="Keine Suchergebnisse!",
                description=f"> Für `{suchbegriff}` wurden keine Kunden gefunden.",
                color=EMBED_COLOR,
                timestamp=get_now(),
            )
            embed.add_field(
                name="Suchtipps",
                value="> `-` Kunden-ID: `VN-26123456`\n> `-` RP-Name: `Max Mustermann`\n> `-` Kartennummer",
                inline=False,
            )
            await interaction.followup.send(ephemeral=True, **ev(embed))
            return

        embed = DEmbed(
            title="Suchergebnisse",
            description=f"> <:2125search:1522597748631801861> `{suchbegriff}`\n> <:3084channelsandroles:1522597765794758810> `{len(treffer)}` Treffer",
            color=EMBED_COLOR,
            timestamp=get_now(),
        )
        for cid, c in treffer[:10]:
            status_text = (
                "<:1571verifieddark:1522597740855689340> Aktiver Kunde!"
                if c.get("status") == "aktiv"
                else "<:archiviert:1522597781557219448> Archivierter Kunde!"
            )
            thread_id = c.get("thread_id")
            versicherungen = (
                "\n".join(f"> ▸ {ins}" for ins in c.get("versicherungen", []))
                or "> `-` *Keine Versicherungen abgeschlossen!*"
            )
            embed.add_field(
                name=f"{c['rp_name']}",
                value=(
                    f"> <:id:1522597735205830666> `{cid}`\n"
                    f"> <:hbpay:1522597775647178905> `{c['hbpay_nummer']}`\n"
                    f"> {status_text}\n"
                    f"> <:6509addguild:1522597829917413396> `{c.get('total_monthly_price', 0):,.2f}€/Monat`\n"
                    + versicherungen[:200]
                    + "\n"
                    + (
                        f"> <:8312activethreads:1522597862779785276> <#{thread_id}>"
                        if thread_id
                        else "> <:4727quarantinew:1522597801077506133> *Keine Akte gefunden!*"
                    )
                ),
                inline=False,
            )
        await interaction.followup.send(ephemeral=True, **ev(embed))
    except Exception as e:
        logger.error(f"Kundensuche Fehler: {e}", exc_info=True)
        await interaction.followup.send(
            ephemeral=True, **ev(build_error_embed("Fehler!", str(e)))
        )


# ═══════════════════════════════════════════════════════
#   VERSICHERUNG KÜNDIGEN
# ═══════════════════════════════════════════════════════
class KündigungSelect(discord.ui.Select):
    def __init__(self, customer_id: str, customer: dict):
        self.customer_id = customer_id
        ins_types = get_insurance_types()
        options = [
            discord.SelectOption(
                label=ins,
                description=f"Beitrag: {ins_types.get(ins, {}).get('price', 0):,.2f}€/Mo",
                value=ins,
            )
            for ins in customer.get("versicherungen", [])
        ]
        super().__init__(
            placeholder="Zu kündigende Versicherung wählen...",
            min_values=1,
            max_values=len(options),
            options=options,
            custom_id="kündigung_select",
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        for item in view.controls:
            if isinstance(item, discord.ui.Button):
                item.disabled = False
        ins_types = get_insurance_types()
        wegfall = sum(ins_types.get(ins, {}).get("price", 0) for ins in self.values)
        neu_total = max(
            0, data["customers"][self.customer_id]["total_monthly_price"] - wegfall
        )
        e = dvg_embed("Kündigung bestätigen", "> Bitte prüfen Sie die Angaben.")
        e.add_field(
            name="Zu kündigende Versicherungen",
            value="\n".join(f">  {ins}" for ins in self.values),
            inline=False,
        )
        e.add_field(
            name="Beitragsänderung",
            value=f"> Wegfall: `-{wegfall:,.2f}€`\n> Neuer Beitrag: **`{neu_total:,.2f}€`**",
            inline=False,
        )
        await interaction.response.edit_message(**ev(e, view=view))


class KündigungView(EView):
    def __init__(self, customer_id: str, customer: dict):
        super().__init__(timeout=120)
        self.confirmed = False
        self._select = KündigungSelect(customer_id, customer)
        self.add_item(self._select)
        btn = discord.ui.Button(
            label="Kündigung bestätigen",
            style=discord.ButtonStyle.danger,
            disabled=True,
        )
        btn.callback = self._confirm
        self.add_item(btn)

    async def _confirm(self, interaction: discord.Interaction):
        self.confirmed = True
        await interaction.response.defer()
        self.stop()


@bot.tree.command(
    name="versicherung-kuendigen",
    description="Kündigt eine oder mehrere Versicherungen eines Kunden",
)
@app_commands.describe(customer_id="Versicherungsnehmer-ID des Kunden")
@app_commands.autocomplete(customer_id=customer_id_autocomplete)
async def versicherung_kündigen(interaction: discord.Interaction, customer_id: str):
    if not is_mitarbeiter(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!",
                    "Nur Mitarbeiter können Versicherungen kündigen.",
                    "Mitarbeiter",
                )
            ),
        )
        return
    if customer_id not in data["customers"]:
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Nicht gefunden!", f"Keine Kundenakte mit ID `{customer_id}`."
                )
            ),
        )
        return
    customer = data["customers"][customer_id]
    if not customer.get("versicherungen"):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(dvg_embed("Keine Versicherungen!", "> Keine aktiven Versicherungen.")),
        )
        return

    # ── Kündigungsfrist prüfen: mind. 4 bezahlte Rechnungen (4 Monatsbeiträge) ──
    kündigung_erlaubt, paid_count = can_cancel_insurance(customer_id)
    if not kündigung_erlaubt:
        fehlende = 4 - paid_count
        singular = fehlende == 1
        e = dvg_embed(
            "Mindestlaufzeit — Kündigung nicht möglich!",
            f"> Versicherungen können erst nach **4 geleisteten Monatsbeiträgen** gekündigt werden. "
            f"> Diese Regelung schützt vor missbräuchlicher Nutzung des Versicherungsschutzes.",
        )
        e.add_field(
            name="Bezahlte Rechnungen",
            value=f"> `{paid_count}` von `4` erforderlichen",
            inline=True,
        )
        e.add_field(
            name="Verbleibend",
            value=(
                f"> `{fehlende}` weiterer Monatsbeitrag"
                if singular
                else f"> `{fehlende}` weitere Monatsbeiträge"
            ),
            inline=True,
        )
        e.add_field(
            name="Versicherungsnehmer",
            value=f"> {customer['rp_name']} (`{customer_id}`)",
            inline=False,
        )
        await interaction.response.send_message(ephemeral=True, **ev(e))
        return

    ins_types = get_insurance_types()
    ins_text = "\n".join(
        f">  {ins} — `{ins_types.get(ins, {}).get('price', 0):,.2f}€/Mo`"
        for ins in customer.get("versicherungen", [])
    )
    view = KündigungView(customer_id, customer)
    e = dvg_embed(
        "Versicherung kündigen", "> Wählen Sie die zu kündigenden Versicherungen."
    )
    e.add_field(
        name="Versicherungsnehmer",
        value=f"> `-` {customer['rp_name']}\n> `-` `{customer_id}`",
        inline=False,
    )
    e.add_field(name="Aktive Versicherungen", value=ins_text or "> Keine", inline=False)
    e.add_field(
        name="Aktueller Monatsbeitrag",
        value=f">  **`{customer.get('total_monthly_price', 0):,.2f}€`**",
        inline=False,
    )
    await interaction.response.send_message(ephemeral=True, **ev(e, view=view))
    await view.wait()

    if not view.confirmed:
        await interaction.edit_original_response(
            **ev(dvg_embed("Kündigung abgebrochen."))
        )
        return

    to_cancel = view._select.values
    if not to_cancel:
        return

    wegfall = sum(ins_types.get(ins, {}).get("price", 0) for ins in to_cancel)
    for ins in to_cancel:
        if ins in data["customers"][customer_id]["versicherungen"]:
            data["customers"][customer_id]["versicherungen"].remove(ins)
        data["customers"][customer_id].get("auszahlungen", {}).pop(ins, None)

    new_total = sum(
        ins_types.get(ins, {}).get("price", 0)
        for ins in data["customers"][customer_id]["versicherungen"]
    )
    data["customers"][customer_id]["total_monthly_price"] = new_total
    save_data(data)
    await update_forum_thread_embed(
        interaction.guild, customer_id, data["customers"][customer_id]
    )

    member = interaction.guild.get_member(customer["discord_user_id"])
    if member:
        for ins in to_cancel:
            role = discord.utils.get(
                interaction.guild.roles, name=ins_types.get(ins, {}).get("role", ins)
            )
            if role and role in member.roles:
                await member.remove_roles(role)
        if not data["customers"][customer_id]["versicherungen"]:
            kunden_role = discord.utils.get(
                interaction.guild.roles, name=KUNDEN_ROLE_NAME
            )
            if kunden_role and kunden_role in member.roles:
                await member.remove_roles(kunden_role)

    thread_id = customer.get("thread_id")
    if thread_id:
        try:
            thread = interaction.guild.get_thread(
                thread_id
            ) or await interaction.guild.fetch_channel(thread_id)
            if thread:
                v = dvg_embed("Kündigungsvermerk")
                v.add_field(
                    name="Gekündigte Versicherungen",
                    value="\n".join(f">  {ins}" for ins in to_cancel),
                    inline=False,
                )
                v.add_field(
                    name="Neuer Monatsbeitrag",
                    value=f"> `{new_total:,.2f}€`",
                    inline=True,
                )
                v.add_field(
                    name="Durchgeführt von",
                    value=f"> {interaction.user.mention}",
                    inline=True,
                )
                await thread.send(**ev(v))
        except Exception as e:
            logger.error(f"Thread-Eintrag Fehler: {e}")

    if member:
        dm = dvg_embed(
            "Versicherungskündigung", "> Folgende Versicherungen wurden entfernt."
        )
        dm.add_field(
            name="Gekündigte Versicherungen",
            value="\n".join(f">  {ins}" for ins in to_cancel),
            inline=False,
        )
        dm.add_field(
            name="Neuer Monatsbeitrag", value=f"> `{new_total:,.2f}€`", inline=False
        )
        try:
            await member.send(**ev(dm))
        except discord.Forbidden:
            pass

    add_log_entry(
        "VERSICHERUNG_GEKUENDIGT",
        interaction.user.id,
        {
            "customer_id": customer_id,
            "gekuendigte_versicherungen": list(to_cancel),
            "neuer_beitrag": new_total,
        },
    )
    log_e = dvg_embed("Versicherung(en) gekündigt!")
    log_e.add_field(
        name="Versicherungsnehmer",
        value=f"> {customer['rp_name']}\n> `{customer_id}`",
        inline=False,
    )
    log_e.add_field(
        name="Gekündigt",
        value="\n".join(f">  {ins}" for ins in to_cancel),
        inline=False,
    )
    log_e.add_field(name="Neuer Beitrag", value=f"> `{new_total:,.2f}€`", inline=True)
    log_e.add_field(
        name="Durchgeführt von", value=f"> {interaction.user.mention}", inline=True
    )
    await send_to_log_channel(interaction.guild, log_e)

    s = dvg_embed(
        "Versicherung(en) gekündigt!", "> Die Kündigung wurde erfolgreich durchgeführt."
    )
    s.add_field(
        name="Versicherungsnehmer",
        value=f"> {customer['rp_name']}\n> `{customer_id}`",
        inline=False,
    )
    s.add_field(
        name="Gekündigt",
        value="\n".join(f">  {ins}" for ins in to_cancel),
        inline=False,
    )
    s.add_field(
        name="Neuer Monatsbeitrag", value=f">  **`{new_total:,.2f}€`**", inline=False
    )
    await interaction.edit_original_response(**ev(s))


# ═══════════════════════════════════════════════════════
#   RECHNUNGEN-ÜBERSICHT
# ═══════════════════════════════════════════════════════
@bot.tree.command(
    name="rechnungen-uebersicht",
    description="Zeigt alle Rechnungen eines Kunden oder alle offenen Rechnungen",
)
@app_commands.describe(
    customer_id="Versicherungsnehmer-ID (leer = alle offenen)",
    nur_offen="Nur offene Rechnungen anzeigen",
)
async def rechnungen_Übersicht(
    interaction: discord.Interaction,
    customer_id: Optional[str] = None,
    nur_offen: bool = True,
):
    if not is_leitungsebene(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!",
                    "Nur die Leitungsebene kann Rechnungsübersichten einsehen.",
                    "Leitungsebene",
                )
            ),
        )
        return
    await interaction.response.defer(ephemeral=True)
    try:
        if customer_id and customer_id not in data["customers"]:
            await interaction.followup.send(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
                    )
                ),
            )
            return
        gefiltert = {
            inv_id: inv
            for inv_id, inv in data["invoices"].items()
            if (not customer_id or inv["customer_id"] == customer_id)
            and (not nur_offen or not inv.get("paid", False))
        }
        if not gefiltert:
            await interaction.followup.send(
                ephemeral=True,
                **ev(dvg_embed("Keine Rechnungen", "> Keine Rechnungen gefunden.")),
            )
            return

        sorted_inv = sorted(
            gefiltert.items(), key=lambda x: x[1].get("created_at", ""), reverse=True
        )
        embed = DEmbed(
            title="Rechnungsübersicht",
            description=(
                (
                    f"> Kunde: **{data['customers'][customer_id]['rp_name']}** (`{customer_id}`)\n"
                    if customer_id
                    else ""
                )
                + f"> Gefunden: **`{len(sorted_inv)}`** Rechnung(en)\n> Filter: `{'Nur offen' if nur_offen else 'Alle'}`"
            ),
            color=EMBED_COLOR,
            timestamp=get_now(),
        )
        total_offen = 0.0
        for inv_id, inv in sorted_inv[:15]:
            cust = data["customers"].get(inv["customer_id"], {})
            due = make_aware(datetime.fromisoformat(inv["due_date"]))
            now = get_now()
            if inv.get("paid"):
                status_text = " Bezahlt"
            elif due < now:
                status_text = f" **{(now - due).days} Tag(e) überfällig!**"
                total_offen += inv["betrag"]
            else:
                status_text = " Ausstehend"
                total_offen += inv["betrag"]
            mahn = inv.get("reminder_count", 0)
            embed.add_field(
                name=f"`{inv_id}`",
                value=(
                    f"> `-` {cust.get('rp_name', '—')}\n"
                    f"> `-` `{inv['betrag']:,.2f}€`\n"
                    f"> Fällig: `{due.strftime('%d.%m.%Y')}`\n"
                    f">  {status_text}"
                    + (f"\n> Mahnstufe: `{mahn}`" if mahn > 0 else "")
                ),
                inline=True,
            )
        embed.add_field(
            name="Offene Summe", value=f"> **`{total_offen:,.2f}€`**", inline=False
        )
        await interaction.followup.send(ephemeral=True, **ev(embed))
    except Exception as e:
        logger.error(f"Rechnungsübersicht Fehler: {e}", exc_info=True)
        await interaction.followup.send(
            ephemeral=True, **ev(build_error_embed("Fehler!", str(e)))
        )


# ═══════════════════════════════════════════════════════
#   ADMIN EINSTELLUNGEN
# ═══════════════════════════════════════════════════════
@bot.tree.command(
    name="einstellung-steuer",
    description="[ADMIN] Setzt den globalen Steuersatz für Rechnungen",
)
@app_commands.describe(prozent="Steuersatz in Prozent (z.B. 5.0)")
async def set_steuer(interaction: discord.Interaction, prozent: float):
    if not is_admin(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!", "Nur Administratoren.", "Administrator"
                )
            ),
        )
        return
    if not (0 <= prozent <= 100):
        await interaction.response.send_message(
            ephemeral=True, **ev(build_error_embed("Ungültiger Wert!", "0–100."))
        )
        return
    config["steuer_prozent"] = prozent
    save_config(config)
    e = DEmbed(
        title="Steuersatz aktualisiert!",
        description=f"> Neuer Steuersatz: **`{prozent}%`**",
        color=EMBED_COLOR,
    )
    await interaction.response.send_message(ephemeral=True, **ev(e))
    add_log_entry(
        "STEUERSATZ_GEAENDERT", interaction.user.id, {"neuer_steuersatz": prozent}
    )


@bot.tree.command(
    name="einstellung-versicherung-neu",
    description="[ADMIN] Fügt eine neue Versicherungsart hinzu",
)
@app_commands.describe(
    name="Name der Versicherung",
    preis="Monatlicher Beitrag in €",
    auszahlungslimit="Maximaler Auszahlungsbetrag in €",
    rollenname="Discord-Rolle (Standard: gleich wie Name)",
)
async def add_versicherung(
    interaction: discord.Interaction,
    name: str,
    preis: float,
    auszahlungslimit: float,
    rollenname: str = "",
):
    if not is_admin(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!", "Nur Administratoren.", "Administrator"
                )
            ),
        )
        return
    if name in config["insurance_types"]:
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed("Bereits vorhanden!", f"`{name}` existiert bereits.")
            ),
        )
        return
    role = rollenname if rollenname else name
    config["insurance_types"][name] = {
        "price": preis,
        "role": role,
        "auszahlung_limit": auszahlungslimit,
        "enabled": True,
    }
    save_config(config)
    e = dvg_embed("Versicherung hinzugefügt!")
    e.add_field(name="Name", value=f"> `{name}`", inline=False)
    e.add_field(name="Preis", value=f"> `{preis:,.2f}€/Monat`", inline=True)
    e.add_field(name="Limit", value=f"> `{auszahlungslimit:,.2f}€`", inline=True)
    e.add_field(name="Rolle", value=f"> `{role}`", inline=True)
    await interaction.response.send_message(ephemeral=True, **ev(e))
    add_log_entry(
        "VERSICHERUNG_HINZUGEFUEGT",
        interaction.user.id,
        {"name": name, "preis": preis, "limit": auszahlungslimit},
    )


@bot.tree.command(
    name="einstellung-versicherung-edit",
    description="[ADMIN] Bearbeitet eine bestehende Versicherungsart",
)
@app_commands.describe(
    name="Name der Versicherung",
    neuer_preis="Neuer Beitrag (-1 = keine Änderung)",
    neues_limit="Neues Auszahlungslimit (-1 = keine Änderung)",
    aktiviert="Aktivieren/Deaktivieren",
)
async def edit_versicherung(
    interaction: discord.Interaction,
    name: str,
    neuer_preis: float = -1.0,
    neues_limit: float = -1.0,
    aktiviert: Optional[bool] = None,
):
    if not is_admin(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!", "Nur Administratoren.", "Administrator"
                )
            ),
        )
        return
    if name not in config["insurance_types"]:
        await interaction.response.send_message(
            ephemeral=True,
            **ev(build_error_embed("Nicht gefunden!", f"Keine Versicherung `{name}`.")),
        )
        return
    changes = []
    if neuer_preis >= 0.0:
        config["insurance_types"][name]["price"] = neuer_preis
        changes.append(f"Preis: `{neuer_preis:,.2f}€`")
    if neues_limit >= 0.0:
        config["insurance_types"][name]["auszahlung_limit"] = neues_limit
        changes.append(f"Limit: `{neues_limit:,.2f}€`")
    if aktiviert is not None:
        config["insurance_types"][name]["enabled"] = aktiviert
        changes.append(f"Status: `{'Aktiv' if aktiviert else 'Deaktiviert'}`")
    if not changes:
        await interaction.response.send_message(
            ephemeral=True, **ev_text("Keine Änderungen angegeben.")
        )
        return
    save_config(config)
    e = DEmbed(
        title=f"Versicherung `{name}` aktualisiert!",
        description="\n".join(f"> {c}" for c in changes),
        color=EMBED_COLOR,
    )
    await interaction.response.send_message(ephemeral=True, **ev(e))


@bot.tree.command(
    name="einstellung-versicherungen-liste",
    description="[ADMIN] Zeigt alle konfigurierten Versicherungen",
)
async def list_versicherungen(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!", "Nur Administratoren.", "Administrator"
                )
            ),
        )
        return
    e = dvg_embed("Versicherungskonfiguration")
    e.add_field(
        name="Steuersatz",
        value=f"> `{config.get('steuer_prozent', 3.0)}%`",
        inline=False,
    )
    for name, v in config.get("insurance_types", {}).items():
        icon = "" if v.get("enabled", True) else ""
        e.add_field(
            name=f"{icon} {name}",
            value=f"> Preis: `{v['price']:,.2f}€/Mo`\n> Limit: `{v['auszahlung_limit']:,.2f}€`\n> Rolle: `{v['role']}`",
            inline=True,
        )
    await interaction.response.send_message(ephemeral=True, **ev(e))


@bot.tree.command(
    name="einstellung-kanaele",
    description="[ADMIN] Setzt alle Bot-Kanäle & Kategorien und richtet Panels ein",
)
@app_commands.describe(
    log_channel="Log-Kanal",
    kundenkontakt_panel="Kanal für Kundenkontakt-Panel",
    schadensmeldung_panel="Kanal für Schadensmeldungs-Panel",
    auszahlung_kanal="Kanal für Auszahlungsanträge",
    dokumentation_kanal="Kanal für Vorgangsprotokolle (Tickets & Rechnungen)",
    kundenkontakt_kategorie="Kategorie für Kundenkontakt-Tickets",
    schadensmeldung_kategorie="Kategorie für Schadensmeldungs-Tickets",
)
async def set_channels(
    interaction: discord.Interaction,
    log_channel: Optional[discord.TextChannel] = None,
    kundenkontakt_panel: Optional[discord.TextChannel] = None,
    schadensmeldung_panel: Optional[discord.TextChannel] = None,
    auszahlung_kanal: Optional[discord.TextChannel] = None,
    dokumentation_kanal: Optional[discord.TextChannel] = None,
    kundenkontakt_kategorie: Optional[discord.CategoryChannel] = None,
    schadensmeldung_kategorie: Optional[discord.CategoryChannel] = None,
):
    if not is_admin(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!", "Nur Administratoren.", "Administrator"
                )
            ),
        )
        return

    if not any(
        [
            log_channel,
            kundenkontakt_panel,
            schadensmeldung_panel,
            auszahlung_kanal,
            dokumentation_kanal,
            kundenkontakt_kategorie,
            schadensmeldung_kategorie,
        ]
    ):
        e = dvg_embed("Aktuelle Kanal-Konfiguration")

        def ch(cid):
            return f"<#{cid}>" if cid else "`Nicht gesetzt`"

        def cat(cid):
            c = interaction.guild.get_channel(cid) if cid else None
            return f"`{c.name}`" if c else "`Nicht gesetzt`"

        e.add_field(
            name="Log-Kanal", value=ch(config.get("log_channel_id")), inline=True
        )
        e.add_field(
            name="Auszahlung",
            value=ch(config.get("auszahlung_channel_id")),
            inline=True,
        )
        e.add_field(
            name="Dokumentation",
            value=ch(config.get("dokumentation_channel_id")),
            inline=True,
        )
        e.add_field(
            name="Kundenkontakt (Panel)",
            value=ch(config.get("kundenkontakt_channel_id")),
            inline=True,
        )
        e.add_field(
            name="Schadensmeldung (Panel)",
            value=ch(config.get("schadensmeldung_channel_id")),
            inline=True,
        )
        e.add_field(
            name="Kundenkontakt (Kategorie)",
            value=cat(config.get("kundenkontakt_category_id")),
            inline=True,
        )
        e.add_field(
            name="Schadensmeldung (Kategorie)",
            value=cat(config.get("schadensmeldung_category_id")),
            inline=True,
        )
        await interaction.response.send_message(ephemeral=True, **ev(e))
        return

    await interaction.response.defer(ephemeral=True)
    changes = []
    panel_results = []

    if log_channel:
        config["log_channel_id"] = log_channel.id
        changes.append(f"Log-Kanal: {log_channel.mention}")
    if auszahlung_kanal:
        config["auszahlung_channel_id"] = auszahlung_kanal.id
        changes.append(f"Auszahlungs-Kanal: {auszahlung_kanal.mention}")
    if dokumentation_kanal:
        config["dokumentation_channel_id"] = dokumentation_kanal.id
        changes.append(f"Dokumentations-Kanal: {dokumentation_kanal.mention}")
    if kundenkontakt_kategorie:
        config["kundenkontakt_category_id"] = kundenkontakt_kategorie.id
        changes.append(f"KK-Kategorie: `{kundenkontakt_kategorie.name}`")
    if schadensmeldung_kategorie:
        config["schadensmeldung_category_id"] = schadensmeldung_kategorie.id
        changes.append(f"SM-Kategorie: `{schadensmeldung_kategorie.name}`")

    if kundenkontakt_panel:
        try:
            config["kundenkontakt_channel_id"] = kundenkontakt_panel.id
            embed_kk = dvg_embed(
                "Kundenkontakt",
                "Liebe Mitarbeiter:innen,\n> hier können sie mit unseren Kunden Kontakt aufnehmen.",
            )
            embed_kk.add_field(
                name="Wie funktioniert das System?",
                value="> 1. Klicken Sie unten auf den Button!\n> 2. Geben Sie die Kunden-ID ein!\n> 3. Beschreiben Sie einen detaillierten Kontaktgrund!\n> 4. Ein privater Ticket-Channel wird erstellt!",
                inline=False,
            )
            embed_kk.add_field(
                name="Was muss ich beachten?",
                value="> `-` Gültige **Kunden-ID** erforderlich!\n> `-` Kontaktgrund **detailliert** beschreiben!\n> `-` Nur für **Mitarbeiter** und **Leitungsebene**!\n> `-` Pro Mitarbeiter nur **ein aktives Ticket** gleichzeitig!",
                inline=False,
            )
            embed_kk.big = True
            await kundenkontakt_panel.send(**ev(embed_kk, view=KundenkontaktView()))
            changes.append(f"KK-Panel: {kundenkontakt_panel.mention}")
            panel_results.append(f" Kundenkontakt-Panel gesendet")
        except Exception as ex:
            panel_results.append(f" Fehler KK-Panel: {ex}")

    if schadensmeldung_panel:
        try:
            config["schadensmeldung_channel_id"] = schadensmeldung_panel.id
            embed_sm = build_schadensmeldung_panel_embed()
            await schadensmeldung_panel.send(**ev(embed_sm, view=SchadensmeldungView()))
            changes.append(f"SM-Panel: {schadensmeldung_panel.mention}")
            panel_results.append(f" Schadensmeldungs-Panel gesendet")
        except Exception as ex:
            panel_results.append(f" Fehler SM-Panel: {ex}")

    save_config(config)
    add_log_entry("KANAELE_KONFIGURIERT", interaction.user.id, {"changes": changes})
    e = dvg_embed("Konfiguration aktualisiert!")
    if changes:
        e.add_field(
            name="Gespeicherte Einstellungen",
            value="\n".join(f"> {c}" for c in changes),
            inline=False,
        )
    if panel_results:
        e.add_field(
            name="Panel-Status",
            value="\n".join(f"> {r}" for r in panel_results),
            inline=False,
        )
    await interaction.followup.send(ephemeral=True, **ev(e))


# ═══════════════════════════════════════════════════════
#   KUNDENAKTE ERSTELLEN
# ═══════════════════════════════════════════════════════
class InsuranceSelect(discord.ui.Select):
    def __init__(self):
        ins_types = get_insurance_types()
        options = [
            discord.SelectOption(
                label=ins,
                description=f"Monatsbeitrag: {info['price']:,.2f}€",
                value=ins,
            )
            for ins, info in ins_types.items()
        ]
        super().__init__(
            placeholder="Gewünschte Versicherungen auswählen...",
            min_values=1,
            max_values=len(options),
            options=options,
            custom_id="insurance_select",
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        for item in view.controls:
            if isinstance(item, discord.ui.Button):
                item.disabled = False
        ins_types = get_insurance_types()
        total = sum(ins_types[ins]["price"] for ins in self.values)
        preview = "\n".join(
            f"> <:1821serversfolder:1522597744030777405> {ins} — {ins_types[ins]['price']:,.2f}€"
            for ins in self.values
        )
        e = DEmbed(
            title="Versicherungen ausgewählt!",
            description=f"{preview}\n\n**Gesamtbeitrag:** `{total:,.2f}€`",
            color=EMBED_COLOR,
        )
        e.set_footer(text="Klicken Sie auf 'Kundenakte erstellen', um fortzufahren.")
        await interaction.response.edit_message(**ev(e, view=view))


class InsuranceView(EView):
    def __init__(self):
        super().__init__(timeout=180)
        self.confirmed = False
        self.add_item(InsuranceSelect())
        btn = discord.ui.Button(
            label="Kundenakte erstellen",
            style=discord.ButtonStyle.green,
            custom_id="confirm_insurance",
            disabled=True,
        )
        btn.callback = self.confirm_callback
        self.add_item(btn)

    async def confirm_callback(self, interaction: discord.Interaction):
        self.confirmed = True
        await interaction.response.defer()
        self.stop()


class AddInsuranceSelect(discord.ui.Select):
    def __init__(self, existing_insurances: list):
        ins_types = get_insurance_types()
        options = [
            discord.SelectOption(
                label=ins,
                description=f"Monatsbeitrag: {info['price']:,.2f}€",
                value=ins,
            )
            for ins, info in ins_types.items()
            if ins not in existing_insurances
        ]
        super().__init__(
            placeholder="Neue Versicherung(en) wählen...",
            min_values=1,
            max_values=len(options),
            options=options,
            custom_id="add_insurance_select",
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        for item in view.controls:
            if isinstance(item, discord.ui.Button):
                item.disabled = False
        ins_types = get_insurance_types()
        total = sum(ins_types[ins]["price"] for ins in self.values)
        e = DEmbed(
            title="Neue Versicherungen ausgewählt!",
            description="\n".join(
                f"> `-` {ins} — {ins_types[ins]['price']:,.2f}€" for ins in self.values
            )
            + f"\n\n**Zusätzlicher Beitrag:** `{total:,.2f}€`",
            color=EMBED_COLOR,
        )
        await interaction.response.edit_message(**ev(e, view=view))


class AddInsuranceView(EView):
    def __init__(self, existing_insurances: list):
        super().__init__(timeout=180)
        self.confirmed = False
        self.add_item(AddInsuranceSelect(existing_insurances))
        btn = discord.ui.Button(
            label="Versicherungen hinzubuchen",
            style=discord.ButtonStyle.green,
            disabled=True,
        )
        btn.callback = self._confirm
        self.add_item(btn)

    async def _confirm(self, interaction: discord.Interaction):
        self.confirmed = True
        await interaction.response.defer()
        self.stop()


@bot.tree.command(
    name="kundenakte-erstellen", description="Erstellt eine neue Kundenakte im Archiv"
)
@app_commands.describe(
    forum_channel="Forum-Channel für Kundenakten",
    user="Discord-User des Versicherungsnehmers",
    rp_name="RP-Name",
    hbpay_nummer="HBpay Kontonummer",
)
async def create_customer(
    interaction: discord.Interaction,
    forum_channel: discord.ForumChannel,
    user: discord.Member,
    rp_name: str,
    hbpay_nummer: str,
):
    if not is_mitarbeiter(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!",
                    "Nur Mitarbeiter.",
                    "Mitarbeiter / Leitungsebene",
                )
            ),
        )
        return
    view = InsuranceView()
    select_embed = dvg_embed(
        "Versicherungen auswählen!",
        "> Bitte wählen Sie die gewünschten Versicherungen aus dem Dropdown-Menü.",
    )
    await interaction.response.send_message(
        ephemeral=True, **ev(select_embed, view=view)
    )
    await view.wait()
    if not view.confirmed:
        await interaction.edit_original_response(**ev(dvg_embed("Zeitüberschreitung!")))
        return
    ins_list = view.controls[0].values
    if not ins_list:
        await interaction.edit_original_response(**ev(dvg_embed("Keine Auswahl!")))
        return

    ins_types = get_insurance_types()
    try:
        customer_id = generate_customer_id()
        total_price = sum(ins_types[ins]["price"] for ins in ins_list)
        customer_data = {
            "rp_name": rp_name,
            "hbpay_nummer": hbpay_nummer,
            "versicherungen": ins_list,
            "total_monthly_price": total_price,
            "thread_id": None,
            "discord_user_id": user.id,
            "created_at": get_now().isoformat(),
            "created_by": interaction.user.id,
            "status": "aktiv",
            "auszahlungen": {},
        }
        embed = build_kundenakte_embed(customer_id, customer_data)
        thread = await forum_channel.create_thread(
            name=f" {customer_id} | {rp_name}", **ev(embed, ping=user.mention)
        )
        customer_data["thread_id"] = thread.thread.id
        data["customers"][customer_id] = customer_data
        save_data(data)

        for insurance in ins_list:
            role_name = ins_types[insurance]["role"]
            role = discord.utils.get(interaction.guild.roles, name=role_name)
            if not role:
                role = await interaction.guild.create_role(
                    name=role_name, color=discord.Color.from_rgb(44, 62, 80)
                )
            await user.add_roles(role)
        kunden_role = discord.utils.get(interaction.guild.roles, name=KUNDEN_ROLE_NAME)
        if not kunden_role:
            kunden_role = await interaction.guild.create_role(
                name=KUNDEN_ROLE_NAME, color=discord.Color.from_rgb(52, 152, 219)
            )
        await user.add_roles(kunden_role)

        # ── Willkommensnachricht per DM ─────────────────────────────────────────
        dm_embed = build_kundenakte_embed(customer_id, customer_data)
        dm_embed.title = "Willkommen der DVG!"
        dm_embed.description = "Ihre Versicherungsakte wurde erfolgreich angelegt."
        try:
            dm_msg = await user.send(**ev(dm_embed))
            customer_data["dm_message_ids"] = [dm_msg.id]
        except discord.Forbidden:
            pass
        save_data(data)

        add_log_entry(
            "KUNDENAKTE_ERSTELLT",
            interaction.user.id,
            {
                "customer_id": customer_id,
                "rp_name": rp_name,
                "versicherungen": ins_list,
                "total_price": total_price,
                "thread_id": thread.thread.id,
                "discord_user_id": user.id,
            },
        )
        await update_customer_thread_backup(interaction.guild, customer_id)

        log_e = dvg_embed(
            "Neue Kundenakte erstellt!",
            description="Diese Kundenakte wurde soeben angelegt. Eine Übersicht der wichtigsten Informationen finden Sie nachfolgend aufgelistet.",
        )
        log_e.add_field(
            name="Versicherungsnehmer",
            value=f"> <:member:1522597880437932112> `{rp_name}`\n> <:id:1522597735205830666> `{customer_id}`\n> <:6509addguild:1522597829917413396> `{total_price:,.2f}€/Monat`",
            inline=False,
        )
        log_e.add_field(
            name="Aussteller",
            value=f"> <:mitarbeiter:1522597807352057928> {interaction.user.mention}",
            inline=False,
        )
        await send_to_log_channel(interaction.guild, log_e)

        s = dvg_embed(
            "Kundenakte erfolgreich angelegt!",
            description="Diese Kundenakte wurde soeben angelegt. Eine Übersicht der wichtigsten Informationen finden Sie nachfolgend aufgelistet.",
        )
        s.add_field(
            name="Informationen",
            value=f"> <:id:1522597735205830666> `{customer_id}`\n> <:8312activethreads:1522597862779785276> {thread.thread.mention}\n> <:6509addguild:1522597829917413396> `{total_price:,.2f}€`\n> <:4426news:1522597790897803374> DM gesendet!",
            inline=False,
        )
        await interaction.edit_original_response(**ev(s))
    except Exception as e:
        logger.error(f"Kundenakte Fehler: {e}", exc_info=True)
        await interaction.edit_original_response(
            **ev(DEmbed(title="Fehler!", description=str(e), color=EMBED_COLOR))
        )


# ═══════════════════════════════════════════════════════
#   VERSICHERUNG NACHBUCHEN
# ═══════════════════════════════════════════════════════
@bot.tree.command(
    name="versicherung-hinzubuchen",
    description="Fügt einem bestehenden Kunden eine neue Versicherung hinzu",
)
@app_commands.describe(customer_id="Versicherungsnehmer-ID")
@app_commands.autocomplete(customer_id=customer_id_autocomplete)
async def add_insurance_to_customer(interaction: discord.Interaction, customer_id: str):
    if not is_mitarbeiter(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
                )
            ),
        )
        return
    if customer_id not in data["customers"]:
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
                )
            ),
        )
        return
    customer = data["customers"][customer_id]
    existing = customer.get("versicherungen", [])
    ins_types = get_insurance_types()
    if not [ins for ins in ins_types if ins not in existing]:
        await interaction.response.send_message(
            ephemeral=True, **ev(dvg_embed("Alle Versicherungen abgeschlossen!"))
        )
        return
    view = AddInsuranceView(existing)
    e = DEmbed(
        title="Versicherung nachbuchen",
        description=f"Kunde: **{customer['rp_name']}** (`{customer_id}`)\n\nBitte wähle die hinzuzufügenden Versicherungen.",
        color=EMBED_COLOR,
    )
    await interaction.response.send_message(ephemeral=True, **ev(e, view=view))
    await view.wait()
    if not view.confirmed:
        await interaction.edit_original_response(**ev(dvg_embed("Abgebrochen.")))
        return
    new_insurances = view.controls[0].values
    if not new_insurances:
        return
    for ins in new_insurances:
        if ins not in data["customers"][customer_id]["versicherungen"]:
            data["customers"][customer_id]["versicherungen"].append(ins)
    new_total = sum(
        ins_types[ins]["price"]
        for ins in data["customers"][customer_id]["versicherungen"]
    )
    data["customers"][customer_id]["total_monthly_price"] = new_total
    save_data(data)
    await update_forum_thread_embed(
        interaction.guild, customer_id, data["customers"][customer_id]
    )
    member = interaction.guild.get_member(customer["discord_user_id"])
    if member:
        for ins in new_insurances:
            role = discord.utils.get(
                interaction.guild.roles, name=ins_types[ins]["role"]
            )
            if not role:
                role = await interaction.guild.create_role(
                    name=ins_types[ins]["role"],
                    color=discord.Color.from_rgb(44, 62, 80),
                )
            await member.add_roles(role)
        dm = dvg_embed(
            "Versicherungsänderung", "Neue Versicherungen wurden hinzugefügt."
        )
        dm.add_field(
            name="Neue Versicherungen",
            value="\n".join(
                f"> <:6509addguild:1522597829917413396> {ins}" for ins in new_insurances
            ),
            inline=False,
        )
        dm.add_field(
            name="Monatsbeitrag (aktualisiert)",
            value=f"> <:einzahlung:1522597871051079710> `{new_total:,.2f}€`",
            inline=False,
        )
        try:
            await member.send(**ev(dm))
        except discord.Forbidden:
            pass
    add_log_entry(
        "VERSICHERUNG_NACHGEBUCHT",
        interaction.user.id,
        {"customer_id": customer_id, "neue_versicherungen": new_insurances},
    )
    await update_customer_thread_backup(interaction.guild, customer_id)
    s = dvg_embed("Versicherungen nachgebucht!")
    s.add_field(
        name="Neue Versicherungen",
        value="\n".join(
            f"> <:6509addguild:1522597829917413396> {ins}" for ins in new_insurances
        ),
        inline=False,
    )
    s.add_field(
        name="Monatsbeitrag (aktualisiert)",
        value=f"> <:einzahlung:1522597871051079710> `{new_total:,.2f}€`",
        inline=False,
    )
    await interaction.edit_original_response(**ev(s))


# ═══════════════════════════════════════════════════════
#   RECHNUNG AUSSTELLEN
# ═══════════════════════════════════════════════════════
@bot.tree.command(
    name="rechnung-ausstellen", description="Erstellt eine Versicherungsrechnung"
)
@app_commands.describe(
    customer_id="Versicherungsnehmer-ID", channel="Channel für die Rechnungsstellung"
)
@app_commands.autocomplete(customer_id=customer_id_autocomplete)
async def create_invoice(
    interaction: discord.Interaction, customer_id: str, channel: discord.TextChannel
):
    if not is_mitarbeiter(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
                )
            ),
        )
        return
    await interaction.response.defer(ephemeral=True)
    try:
        if customer_id not in data["customers"]:
            await interaction.followup.send(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
                    )
                ),
            )
            return
        customer = data["customers"][customer_id]

        # Prüfen ob bereits eine offene Rechnung existiert
        existing_inv = customer_has_unpaid_invoice(customer_id)
        if existing_inv:
            await interaction.followup.send(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Offene Rechnung vorhanden!",
                        f"Für **{customer['rp_name']}** existiert bereits eine offene Rechnung (`{existing_inv}`).\nBitte archivieren Sie diese zuerst, bevor eine neue ausgestellt werden kann.",
                    )
                ),
            )
            return

        invoice_id = generate_invoice_id()
        betrag_netto = customer["total_monthly_price"]
        steuer_prozent = config.get("steuer_prozent", 3.0)
        steuer = betrag_netto * (steuer_prozent / 100)
        betrag_brutto = betrag_netto + steuer
        due_date = get_now() + timedelta(days=3)
        ins_types = get_insurance_types()

        embed = DEmbed(
            title=f"Versicherungsrechnung - {get_now().strftime('%d.%m.%Y')}",
            description="Dies ist eine Zahlungsaufforderung für Ihre Versicherungsbeiträge!",
            color=EMBED_COLOR,
            timestamp=get_now(),
        )
        embed.big = True
        embed.add_field(
            name="Rechnungsinformationen",
            value=f"> <:id:1522597735205830666> `{invoice_id}`",
        )
        embed.add_field(
            name="Versicherungsnehmer",
            value=f"> <:member:1522597880437932112> {customer['rp_name']}\n> <:id:1522597735205830666> `{customer_id}`",
            inline=False,
        )
        embed.add_field(
            name="Zahlungsmethode",
            value=f"> <:hbpay:1522597775647178905> `{customer['hbpay_nummer']}`",
            inline=False,
        )
        ins_details = "\n".join(
            f"> {ins}\n> ▸ `{ins_types.get(ins, {}).get('price', 0.0):,.2f}€`"
            for ins in customer["versicherungen"]
        )
        embed.add_field(
            name="Abgeschlossene Versicherungen", value=ins_details, inline=False
        )
        embed.add_field(
            name="Zwischensumme (Netto)",
            value=f"> `{betrag_netto:,.2f}€`",
            inline=False,
        )
        embed.add_field(
            name=f"Steuer ({steuer_prozent}%)",
            value=f"> `+ {steuer:,.2f}€`",
            inline=False,
        )
        embed.add_field(
            name="Rechnungsbetrag (Brutto)",
            value=f" <:8558viewasrolearrow:1522597865350889472> **`{betrag_brutto:,.2f}€`**",
            inline=False,
        )
        embed.add_field(
            name="Status: Zahlung ausstehend!",
            value=f"> <:9708withoutavoice:1522597896086618292> **{due_date.strftime('%d.%m.%Y')}**",
            inline=False,
        )

        message = await channel.send(**ev(embed))
        data["invoices"][invoice_id] = {
            "customer_id": customer_id,
            "betrag": betrag_brutto,
            "betrag_netto": betrag_netto,
            "steuer": steuer,
            "steuer_prozent": steuer_prozent,
            "original_betrag": betrag_brutto,
            "paid": False,
            "message_id": message.id,
            "channel_id": channel.id,
            "due_date": due_date.isoformat(),
            "reminder_count": 0,
            "created_at": get_now().isoformat(),
            "created_by": interaction.user.id,
        }
        save_data(data)
        add_log_entry(
            "RECHNUNG_ERSTELLT",
            interaction.user.id,
            {
                "invoice_id": invoice_id,
                "customer_id": customer_id,
                "betrag_brutto": betrag_brutto,
            },
        )
        await update_customer_thread_backup(interaction.guild, customer_id)

        # Dokumentationskanal-Eintrag
        await send_to_dokumentation_channel(
            interaction.guild,
            interaction.user,
            vorgang=f"`{invoice_id}`",
            anliegen=f"`{betrag_brutto:,.2f}€` — {customer['rp_name']} (`{customer_id}`)",
        )

        s = dvg_embed("Rechnung erfolgreich ausgestellt!")
        s.add_field(name="Rechnungsnummer", value=f"> `{invoice_id}`", inline=True)
        s.add_field(name="Betrag", value=f"> `{betrag_brutto:,.2f}€`", inline=True)
        s.add_field(
            name="Fällig", value=f"> {due_date.strftime('%d.%m.%Y')}", inline=True
        )
        await interaction.followup.send(ephemeral=True, **ev(s))
    except Exception as e:
        logger.error(f"Rechnung Fehler: {e}", exc_info=True)
        await interaction.followup.send(
            ephemeral=True, **ev(build_error_embed("Fehler!", str(e)))
        )


# ═══════════════════════════════════════════════════════
#   RECHNUNG ARCHIVIEREN
# ═══════════════════════════════════════════════════════
@bot.tree.command(
    name="rechnung-archivieren",
    description="Markiert eine Rechnung als bezahlt – setzt das Auszahlungslimit zurück",
)
@app_commands.describe(invoice_id="Rechnungsnummer (z.B. RE-2412-A3F9)")
@app_commands.autocomplete(invoice_id=invoice_id_autocomplete)
async def archive_invoice(interaction: discord.Interaction, invoice_id: str):
    if not is_mitarbeiter(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
                )
            ),
        )
        return
    await interaction.response.defer(ephemeral=True)
    try:
        if invoice_id not in data["invoices"]:
            await interaction.followup.send(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Nicht gefunden!", f"Keine Rechnung `{invoice_id}`."
                    )
                ),
            )
            return
        invoice = data["invoices"][invoice_id]
        if invoice.get("paid", False):
            await interaction.followup.send(
                ephemeral=True, **ev(dvg_embed("Bereits archiviert!"))
            )
            return
        customer_id = invoice["customer_id"]
        customer = data["customers"].get(customer_id)
        if not customer:
            await interaction.followup.send(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Nicht gefunden!", f"Kunde `{customer_id}` nicht gefunden."
                    )
                ),
            )
            return

        data["invoices"][invoice_id].update(
            {
                "paid": True,
                "paid_by": interaction.user.id,
                "paid_at": get_now().isoformat(),
                "archived": True,
                "reminder_count": 0,
            }
        )
        data["customers"][customer_id]["auszahlungen"] = {}
        save_data(data)

        try:
            ch = interaction.guild.get_channel(invoice["channel_id"])
            if ch:
                msg = await ch.fetch_message(invoice["message_id"])
                await msg.edit(
                    **restyle(
                        msg,
                        fields=[
                            (
                                "Status",
                                "Status: Bezahlt!",
                                f"> <:datetime:1522597873286512777> **{get_now().strftime('%d.%m.%Y, %H:%M Uhr')}**\n> <:5554authapppermission:1522597727341646024> {interaction.user.mention}",
                            )
                        ],
                        color=COLOR_SUCCESS,
                    )
                )
        except Exception as ex:
            logger.error(f"Rechnung Update Fehler: {ex}")

        thread_id = customer.get("thread_id")
        if thread_id:
            try:
                thread = interaction.guild.get_thread(
                    thread_id
                ) or await interaction.guild.fetch_channel(thread_id)
                if thread:
                    ae = dvg_embed(
                        "Archivierte Rechnung",
                        "Auszahlungslimit zurückgesetzt.",
                    )
                    ae.add_field(
                        name="Rechnungsnr.",
                        value=f"> <:id:1522597735205830666> `{invoice_id}`",
                        inline=False,
                    )
                    ae.add_field(
                        name="Rechnungsbetrag",
                        value=f"> <:einzahlung:1522597871051079710> `{invoice['betrag']:,.2f}€`",
                        inline=True,
                    )
                    ae.add_field(
                        name="Archiviert von",
                        value=f"> <:archiviert:1522597781557219448> {interaction.user.mention}",
                        inline=False,
                    )
                    await thread.send(**ev(ae))
            except Exception as ex:
                logger.error(f"Thread Eintrag Fehler: {ex}")

        add_log_entry(
            "RECHNUNG_ARCHIVIERT",
            interaction.user.id,
            {
                "invoice_id": invoice_id,
                "customer_id": customer_id,
                "betrag": invoice["betrag"],
            },
        )
        await update_customer_thread_backup(interaction.guild, customer_id)

        s = DEmbed(
            title="Rechnung archiviert!",
            description=f"`{invoice_id}` als bezahlt markiert.",
            color=EMBED_COLOR,
        )
        s.add_field(name="Kunde", value=f"> {customer['rp_name']}", inline=True)
        s.add_field(name="Betrag", value=f"> `{invoice['betrag']:,.2f}€`", inline=True)
        await interaction.followup.send(ephemeral=True, **ev(s))
    except Exception as e:
        logger.error(f"Archivieren Fehler: {e}", exc_info=True)
        await interaction.followup.send(
            ephemeral=True, **ev(build_error_embed("Fehler!", str(e)))
        )


# ═══════════════════════════════════════════════════════
#   MAHNUNG AUSSTELLEN
# ═══════════════════════════════════════════════════════
@bot.tree.command(
    name="mahnung-ausstellen",
    description="Stellt eine Mahnung für eine überfällige Rechnung aus",
)
@app_commands.describe(invoice_id="Rechnungsnummer")
@app_commands.autocomplete(invoice_id=invoice_id_autocomplete)
async def issue_manual_reminder(interaction: discord.Interaction, invoice_id: str):
    if not is_mitarbeiter(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
                )
            ),
        )
        return
    await interaction.response.defer(ephemeral=True)
    try:
        if invoice_id not in data["invoices"]:
            await interaction.followup.send(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Nicht gefunden!", f"Keine Rechnung `{invoice_id}`."
                    )
                ),
            )
            return
        invoice = data["invoices"][invoice_id]
        if invoice.get("paid", False):
            await interaction.followup.send(
                ephemeral=True, **ev(dvg_embed("Bereits bezahlt!"))
            )
            return
        customer = data["customers"].get(invoice["customer_id"])
        if not customer:
            await interaction.followup.send(
                ephemeral=True,
                **ev(build_error_embed("Nicht gefunden!", "Kunde nicht gefunden.")),
            )
            return

        reminder_count = invoice.get("reminder_count", 0) + 1
        surcharge_pct = 0
        if reminder_count == 2:
            surcharge_pct = 5
            data["invoices"][invoice_id]["betrag"] = invoice["original_betrag"] * 1.05
        elif reminder_count >= 3:
            surcharge_pct = 10
            data["invoices"][invoice_id]["betrag"] = invoice["original_betrag"] * 1.10
        data["invoices"][invoice_id]["reminder_count"] = reminder_count
        save_data(data)
        await send_reminder(
            invoice_id, data["invoices"][invoice_id], reminder_count, surcharge_pct
        )
        await update_customer_thread_backup(interaction.guild, invoice["customer_id"])

        s = DEmbed(
            title=f"{reminder_count}. Mahnung ausgestellt!",
            description=f"Rechnung `{invoice_id}`",
            color=EMBED_COLOR,
        )
        s.add_field(
            name="Neuer Betrag",
            value=f"> `{data['invoices'][invoice_id]['betrag']:,.2f}€`",
            inline=True,
        )
        if surcharge_pct > 0:
            s.add_field(name="Mahngebühr", value=f"> +{surcharge_pct}%", inline=True)
        await interaction.followup.send(ephemeral=True, **ev(s))
    except Exception as e:
        await interaction.followup.send(
            ephemeral=True, **ev(build_error_embed("Fehler!", str(e)))
        )


async def send_reminder(
    invoice_id: str, invoice_data: dict, reminder_number: int, surcharge_percent: int
):
    try:
        for guild in bot.guilds:
            channel = guild.get_channel(invoice_data["channel_id"])
            customer = data["customers"].get(invoice_data["customer_id"])
            if not channel or not customer:
                continue
            member = guild.get_member(customer["discord_user_id"])
            surcharge_tx = (
                f" (+{surcharge_percent}% Mahngebühr)" if surcharge_percent > 0 else ""
            )
            embed = DEmbed(
                title=f"{reminder_number}. Mahnung",
                description=f"Die Rechnung `{invoice_id}` ist überfällig!",
                color=EMBED_COLOR if reminder_number < 3 else COLOR_ERROR,
                timestamp=get_now(),
            )
            embed.add_field(
                name="Rechnungs-Nr.",
                value=f"> `{invoice_id}`\n> Mahnstufe: {reminder_number}",
                inline=False,
            )
            embed.add_field(
                name="Betrag",
                value=f"> Ursprünglich: `{invoice_data['original_betrag']:,.2f}€`\n> **Aktuell: `{invoice_data['betrag']:,.2f}€`**{surcharge_tx}",
                inline=False,
            )
            await channel.send(**ev(embed, ping=member.mention if member else ""))
            add_log_entry(
                f"MAHNUNG_{reminder_number}",
                0,
                {
                    "invoice_id": invoice_id,
                    "customer_id": invoice_data["customer_id"],
                    "surcharge": surcharge_percent,
                    "neuer_betrag": invoice_data["betrag"],
                },
            )
            break
    except Exception as e:
        logger.error(f"Mahnung Fehler: {e}", exc_info=True)


# ═══════════════════════════════════════════════════════
#   AKTE ARCHIVIEREN
# ═══════════════════════════════════════════════════════
@bot.tree.command(name="akte-archivieren", description="Archiviert eine Kundenakte")
@app_commands.describe(customer_id="Versicherungsnehmer-ID")
@app_commands.autocomplete(customer_id=customer_id_all_autocomplete)
async def archive_customer(interaction: discord.Interaction, customer_id: str):
    if not is_mitarbeiter(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
                )
            ),
        )
        return
    await interaction.response.defer(ephemeral=True)
    try:
        if customer_id not in data["customers"]:
            await interaction.followup.send(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
                    )
                ),
            )
            return
        customer = data["customers"][customer_id]
        if customer.get("status") == "archiviert":
            await interaction.followup.send(
                ephemeral=True, **ev(dvg_embed("Bereits archiviert!"))
            )
            return
        data["customers"][customer_id].update(
            {
                "status": "archiviert",
                "archived_at": get_now().isoformat(),
                "archived_by": interaction.user.id,
            }
        )
        save_data(data)

        thread_id = customer.get("thread_id")
        if thread_id:
            try:
                thread = interaction.guild.get_thread(
                    thread_id
                ) or await interaction.guild.fetch_channel(thread_id)
                if thread:
                    await thread.edit(
                        name=f" [ARCHIV] {customer_id} | {customer['rp_name']}"
                    )
                    ae = dvg_embed(
                        "Akte archiviert!", "Diese Kundenakte wurde archiviert."
                    )
                    ae.add_field(
                        name="Archiviert von",
                        value=f"> {interaction.user.mention}",
                        inline=True,
                    )
                    ae.add_field(
                        name="Datum",
                        value=f"> {get_now().strftime('%d.%m.%Y, %H:%M Uhr')}",
                        inline=True,
                    )
                    await thread.send(**ev(ae))
            except Exception as ex:
                logger.error(f"Thread Update Fehler: {ex}")

        member = interaction.guild.get_member(customer["discord_user_id"])
        ins_types = get_insurance_types()
        if member:
            for insurance in customer.get("versicherungen", []):
                role = discord.utils.get(
                    interaction.guild.roles,
                    name=ins_types.get(insurance, {}).get("role", insurance),
                )
                if role and role in member.roles:
                    await member.remove_roles(role)
            kunden_role = discord.utils.get(
                interaction.guild.roles, name=KUNDEN_ROLE_NAME
            )
            if kunden_role and kunden_role in member.roles:
                await member.remove_roles(kunden_role)

        add_log_entry(
            "AKTE_ARCHIVIERT",
            interaction.user.id,
            {"customer_id": customer_id, "customer_name": customer["rp_name"]},
        )
        await update_customer_thread_backup(interaction.guild, customer_id)

        s = DEmbed(
            title="Akte archiviert!",
            description=f"Kundenakte `{customer_id}` archiviert und alle Rollen entfernt.",
            color=EMBED_COLOR,
        )
        await interaction.followup.send(ephemeral=True, **ev(s))
    except Exception as e:
        logger.error(f"Archivieren Fehler: {e}", exc_info=True)
        await interaction.followup.send(
            ephemeral=True, **ev(build_error_embed("Fehler!", str(e)))
        )


# ═══════════════════════════════════════════════════════
#   AUSZAHLUNG SYSTEM
# ═══════════════════════════════════════════════════════
class AuszahlungAntragsModal(discord.ui.Modal, title="Auszahlungsantrag"):
    betrag = discord.ui.TextInput(
        label="Auszahlungsbetrag (ohne €-Zeichen)",
        placeholder="z.B. 5000.00",
        required=True,
        max_length=20,
    )
    beschreibung = discord.ui.TextInput(
        label="Beschreibung (optional)",
        style=discord.TextStyle.paragraph,
        placeholder="Kurze Beschreibung des Auszahlungsgrunds...",
        required=False,
        max_length=500,
    )

    def __init__(self, customer_id: str, customer: dict, versicherung: str):
        super().__init__()
        self.customer_id = customer_id
        self.customer = customer
        self.versicherung = versicherung

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            try:
                betrag_float = float(
                    self.betrag.value.replace(",", ".").replace("€", "").strip()
                )
            except ValueError:
                await interaction.followup.send(
                    ephemeral=True, **ev_text(" Ungültiger Betrag.")
                )
                return

            verfügbar = get_verfügbares_guthaben(self.customer_id, self.versicherung)
            ins_types = get_insurance_types()
            limit = ins_types.get(self.versicherung, {}).get("auszahlung_limit", 0.0)

            if betrag_float <= 0:
                await interaction.followup.send(
                    ephemeral=True, **ev_text(" Betrag muss > 0 sein.")
                )
                return
            if betrag_float > verfügbar:
                await interaction.followup.send(
                    ephemeral=True,
                    **ev_text(
                        f" Betrag überschreitet verfügbares Guthaben `{verfügbar:,.2f}€`."
                    ),
                )
                return

            az_channel_id = config.get("auszahlung_channel_id")
            if not az_channel_id:
                await interaction.followup.send(
                    ephemeral=True, **ev_text(" Auszahlungs-Kanal nicht konfiguriert.")
                )
                return
            az_channel = interaction.guild.get_channel(az_channel_id)
            if not az_channel:
                await interaction.followup.send(
                    ephemeral=True, **ev_text(" Auszahlungs-Kanal nicht gefunden.")
                )
                return

            auszahlung_id = generate_auszahlung_id()
            beschreibung_tx = (
                self.beschreibung.value.strip() if self.beschreibung.value else "—"
            )
            fkr_roles = _get_roles(interaction.guild, FIRMENKONTOROLLE_ROLE_ID)
            ping_text = (
                " ".join(r.mention for r in fkr_roles)
                if fkr_roles
                else "@Firmenkontorolle"
            )

            embed = dvg_embed("Auszahlungsantrag")
            embed.add_field(
                name="Antragsinformationen",
                value=f"> <:id:1522597735205830666> `{auszahlung_id}`\n> <:auszahlung:1522597847390879794> `{betrag_float:,.2f}€`",
                inline=False,
            )
            embed.add_field(
                name="Versicherungsnehmer",
                value=f"> <:member:1522597880437932112> `{self.customer['rp_name']}`\n> <:id:1522597735205830666> `{self.customer_id}`",
                inline=False,
            )
            embed.add_field(
                name="Versicherung",
                value=f"> {self.versicherung}\n> ▸ `{verfügbar:,.2f}€` von `{limit:,.2f}€` verfügbar!",
                inline=False,
            )
            embed.add_field(
                name="Beschreibung", value=f"```{beschreibung_tx}```", inline=False
            )
            embed.add_field(
                name="Eingereicht von",
                value=f" {interaction.user.mention}",
                inline=True,
            )
            embed.add_field(name="Status", value="Ausstehend!", inline=False)

            action_view = AuszahlungActionView(
                auszahlung_id, self.customer_id, betrag_float
            )
            msg = await az_channel.send(
                **ev(
                    embed,
                    view=action_view,
                    ping=f"{ping_text} — Neuer Auszahlungsantrag!",
                )
            )

            data["pending_auszahlungen"][auszahlung_id] = {
                "customer_id": self.customer_id,
                "versicherung": self.versicherung,
                "betrag": betrag_float,
                "beschreibung": beschreibung_tx,
                "requester_id": interaction.user.id,
                "message_id": msg.id,
                "channel_id": az_channel_id,
                "status": "ausstehend",
                "created_at": get_now().isoformat(),
            }
            save_data(data)
            add_log_entry(
                "AUSZAHLUNG_EINGEREICHT",
                interaction.user.id,
                {
                    "auszahlung_id": auszahlung_id,
                    "customer_id": self.customer_id,
                    "versicherung": self.versicherung,
                    "betrag": betrag_float,
                },
            )

            s = DEmbed(
                title="Auszahlungsantrag eingereicht!",
                description=f"Antrag `{auszahlung_id}` wurde weitergeleitet.",
                color=EMBED_COLOR,
            )
            s.add_field(name="Betrag", value=f"> `{betrag_float:,.2f}€`", inline=True)
            s.add_field(
                name="Versicherung", value=f"> `{self.versicherung}`", inline=True
            )
            await interaction.followup.send(ephemeral=True, **ev(s))
        except Exception as e:
            logger.error(f"Auszahlung Einreichen Fehler: {e}", exc_info=True)
            await interaction.followup.send(ephemeral=True, **ev_text(f" Fehler: {e}"))


class AuszahlungSelectView(EView):
    def __init__(self, customer_id: str, customer: dict):
        super().__init__(timeout=300)
        self.customer_id = customer_id
        ins_types = get_insurance_types()
        options = []
        for versicherung in customer.get("versicherungen", []):
            verfügbar = get_verfügbares_guthaben(customer_id, versicherung)
            limit = ins_types.get(versicherung, {}).get("auszahlung_limit", 0.0)
            bereits = limit - verfügbar
            options.append(
                discord.SelectOption(
                    label=versicherung[:100],
                    description=f"Verfügbar: {verfügbar:,.0f}€ | Ausgezahlt: {bereits:,.0f}€ / {limit:,.0f}€"[
                        :100
                    ],
                    value=versicherung if verfügbar > 0 else "",
                )
            )
        self._select = discord.ui.Select(
            placeholder="Versicherung wählen...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="az_versicherung_select",
        )
        self._select.callback = self._on_select
        self.add_item(self._select)
        self._customer = customer

    async def _on_select(self, interaction: discord.Interaction):
        selected = self._select.values[0]
        verfügbar = get_verfügbares_guthaben(self.customer_id, selected)
        if verfügbar <= 0:
            await interaction.response.send_message(
                ephemeral=True, **ev_text(f"Limit für `{selected}` ausgeschöpft.")
            )
            return
        await interaction.response.send_modal(
            AuszahlungAntragsModal(self.customer_id, self._customer, selected)
        )


class AuszahlungBestätigenModal(
    discord.ui.Modal, title="Auszahlung bestätigen – Nachweis"
):
    auszahlungs_link = discord.ui.TextInput(
        label="Link der Auszahlungsnachricht",
        placeholder="https://discord.com/channels/...",
        required=True,
        max_length=500,
    )

    def __init__(
        self, auszahlung_id: str, guild: discord.Guild, confirmer: discord.Member
    ):
        super().__init__()
        self.auszahlung_id = auszahlung_id
        self.guild = guild
        self.confirmer = confirmer

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            pending = data.get("pending_auszahlungen", {}).get(self.auszahlung_id)
            if not pending or pending.get("status") != "ausstehend":
                await interaction.followup.send(
                    ephemeral=True, **ev_text("Bereits bearbeitet.")
                )
                return
            customer_id = pending["customer_id"]
            versicherung = pending["versicherung"]
            betrag = pending["betrag"]
            customer = data["customers"].get(customer_id)
            if not customer:
                await interaction.followup.send(
                    ephemeral=True, **ev_text("Kunde nicht gefunden.")
                )
                return
            verfügbar = get_verfügbares_guthaben(customer_id, versicherung)
            if betrag > verfügbar:
                await interaction.followup.send(
                    ephemeral=True,
                    **ev_text(
                        f"Guthaben reicht nicht aus (`{verfügbar:,.2f}€` verfügbar)."
                    ),
                )
                return

            if "auszahlungen" not in data["customers"][customer_id]:
                data["customers"][customer_id]["auszahlungen"] = {}
            data["customers"][customer_id]["auszahlungen"][versicherung] = (
                data["customers"][customer_id]["auszahlungen"].get(versicherung, 0.0)
                + betrag
            )
            data["pending_auszahlungen"][self.auszahlung_id].update(
                {
                    "status": "bestätigt",
                    "bestätigt_von": self.confirmer.id,
                    "bestätigt_am": get_now().isoformat(),
                    "auszahlungs_link": self.auszahlungs_link.value,
                }
            )
            save_data(data)

            thread_id = customer.get("thread_id")
            if thread_id:
                try:
                    thread = self.guild.get_thread(
                        thread_id
                    ) or await self.guild.fetch_channel(thread_id)
                    if thread:
                        neues_guthaben = get_verfügbares_guthaben(
                            customer_id, versicherung
                        )
                        ve = dvg_embed("Auszahlungsvermerk")
                        ve.add_field(
                            name="Antragsantrag",
                            value=f"> <:id:1522597735205830666> `{self.auszahlung_id}`\n> <:1821serversfolder:1522597744030777405> `{versicherung}`\n> <:7926copymessagelink:1522597855905316914> [Auszahlungsnachricht]({self.auszahlungs_link.value})",
                            inline=False,
                        )
                        ve.add_field(
                            name="Details",
                            value=f"> Verfügbar: `{verfügbar:,.2f}€`\n> Ausgezahlt: `-{betrag:,.2f}€`\n> **Restguthaben: `{neues_guthaben:,.2f}€`**",
                            inline=False,
                        )
                        await thread.send(**ev(ve))
                except Exception as ex:
                    logger.error(f"Vermerk Fehler: {ex}")

            try:
                az_channel = self.guild.get_channel(pending["channel_id"])
                if az_channel:
                    orig_msg = await az_channel.fetch_message(pending["message_id"])
                    await orig_msg.edit(
                        **restyle(
                            orig_msg,
                            fields=[
                                ("Status", "Status", "Genehmigt!"),
                                (
                                    "Genehmigt von",
                                    "Genehmigt von",
                                    self.confirmer.mention,
                                ),
                            ],
                            color=COLOR_SUCCESS,
                        )
                    )
            except Exception as ex:
                logger.error(f"Antrag Update Fehler: {ex}")

            add_log_entry(
                "AUSZAHLUNG_BESTAETIGT",
                self.confirmer.id,
                {
                    "auszahlung_id": self.auszahlung_id,
                    "customer_id": customer_id,
                    "versicherung": versicherung,
                    "betrag": betrag,
                },
            )
            await update_customer_thread_backup(self.guild, customer_id)

            s = DEmbed(
                title="Auszahlung bestätigt!",
                description=f"Auszahlung `{self.auszahlung_id}` genehmigt.",
                color=EMBED_COLOR,
            )
            s.add_field(name="Betrag", value=f"> `{betrag:,.2f}€`", inline=True)
            await interaction.followup.send(ephemeral=True, **ev(s))
        except Exception as e:
            logger.error(f"Bestätigen Fehler: {e}", exc_info=True)
            await interaction.followup.send(ephemeral=True, **ev_text(f" Fehler: {e}"))


class AuszahlungActionView(EView):
    def __init__(self, auszahlung_id: str, customer_id: str, betrag: float):
        super().__init__(timeout=None)
        self.auszahlung_id = auszahlung_id
        self.customer_id = customer_id
        self.betrag = betrag

    def _get_az_id(self, message: discord.Message) -> str:
        """Findet die Auszahlungs-ID anhand der Nachrichten-ID — zuverlässiger als Embed-Parsing."""
        if message:
            for az_id, az in data.get("pending_auszahlungen", {}).items():
                if az.get("message_id") == message.id:
                    return az_id
        return self.auszahlung_id

    @discord.ui.button(
        label="Bestätigen",
        style=discord.ButtonStyle.green,
        custom_id="auszahlung_bestätigen",
    )
    async def bestätigen(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not is_firmenkontorolle(interaction):
            await interaction.response.send_message(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Zugriff verweigert!",
                        "Nur das Firmenkonto kann Auszahlungsanträge bearbeiten.",
                        "Firmenkonto",
                    )
                ),
            )
            return
        az_id = self._get_az_id(interaction.message)
        pending = data.get("pending_auszahlungen", {}).get(az_id)
        if not pending or pending.get("status") != "ausstehend":
            await interaction.response.send_message(
                ephemeral=True, **ev_text(" Bereits bearbeitet oder nicht gefunden.")
            )
            return
        await interaction.response.send_modal(
            AuszahlungBestätigenModal(az_id, interaction.guild, interaction.user)
        )

    @discord.ui.button(
        label="Abbrechen",
        style=discord.ButtonStyle.danger,
        custom_id="auszahlung_abbrechen",
    )
    async def abbrechen(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not is_firmenkontorolle(interaction):
            await interaction.response.send_message(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Zugriff verweigert!", "Nur das Firmenkonto.", "Firmenkonto"
                    )
                ),
            )
            return
        az_id = self._get_az_id(interaction.message)
        pending = data.get("pending_auszahlungen", {}).get(az_id)
        if not pending or pending.get("status") != "ausstehend":
            await interaction.response.send_message(
                ephemeral=True, **ev_text(" Bereits bearbeitet.")
            )
            return
        data["pending_auszahlungen"][az_id].update(
            {
                "status": "abgelehnt",
                "abgelehnt_von": interaction.user.id,
                "abgelehnt_am": get_now().isoformat(),
            }
        )
        save_data(data)
        try:
            await interaction.message.edit(
                **restyle(
                    interaction.message,
                    fields=[
                        ("Status", "Status", "Abgelehnt!"),
                        ("Abgelehnt von", "Abgelehnt von", interaction.user.mention),
                    ],
                    color=COLOR_ERROR,
                )
            )
        except Exception as ex:
            logger.error(f"Update Fehler: {ex}")
        add_log_entry(
            "AUSZAHLUNG_ABGELEHNT", interaction.user.id, {"auszahlung_id": az_id}
        )
        await interaction.response.send_message(
            ephemeral=True, **ev_text(f"Antrag `{az_id}` wurde abgelehnt.")
        )


@bot.tree.command(
    name="auszahlung-einreichen",
    description="Reicht einen Auszahlungsantrag für einen Kunden ein",
)
@app_commands.describe(customer_id="Versicherungsnehmer-ID")
@app_commands.autocomplete(customer_id=customer_id_autocomplete)
async def auszahlung_einreichen(interaction: discord.Interaction, customer_id: str):
    if not is_mitarbeiter(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
                )
            ),
        )
        return
    if customer_id not in data["customers"]:
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
                )
            ),
        )
        return
    customer = data["customers"][customer_id]
    if not customer.get("versicherungen"):
        await interaction.response.send_message(
            ephemeral=True, **ev_text(" Keine Versicherungen vorhanden.")
        )
        return
    ins_types = get_insurance_types()
    limits_text = ""
    for versicherung in customer.get("versicherungen", []):
        verfügbar = get_verfügbares_guthaben(customer_id, versicherung)
        limit = ins_types.get(versicherung, {}).get("auszahlung_limit", 0.0)
        limits_text += f"**{versicherung}**\n> Verfügbar: `{verfügbar:,.2f} EUR` von `{limit:,.2f} EUR`\n"
    e = dvg_embed(
        "Auszahlungsantrag einreichen",
        f"> Versicherungsnehmer: **{customer['rp_name']}** (`{customer_id}`)",
    )
    e.add_field(
        name="Auszahlungsguthaben", value=limits_text or "> Keine Daten", inline=False
    )
    await interaction.response.send_message(
        ephemeral=True, **ev(e, view=AuszahlungSelectView(customer_id, customer))
    )


# ═══════════════════════════════════════════════════════
#   TICKET SYSTEM — PANELS
# ═══════════════════════════════════════════════════════
class KundenkontaktView(EView):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Kundenkontakt anfragen!",
        style=discord.ButtonStyle.secondary,
        custom_id="open_kundenkontakt",
    )
    async def open_kundenkontakt(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_modal(TicketModal())


class SchadensmeldungView(EView):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Schadensmeldung einreichen!",
        style=discord.ButtonStyle.secondary,
        custom_id="open_schadensmeldung",
    )
    async def open_schadensmeldung(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_modal(SchadensmeldungModal())


# ═══════════════════════════════════════════════════════
#   INAKTIVITÄTS-WARNUNG VIEW
# ═══════════════════════════════════════════════════════
class InaktivitätsWarnView(EView):
    """Persistent View für die 16h-Inaktivitätswarnung."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Automatisches Schließen abbrechen",
        style=discord.ButtonStyle.primary,
        custom_id="cancel_auto_close_btn",
    )
    async def cancel_auto_close(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        ch_key = str(interaction.channel.id)
        ticket_info = data.get("ticket_channels", {}).get(ch_key)

        if not ticket_info:
            await interaction.response.send_message(
                ephemeral=True, **ev_text("Ticket-Daten nicht gefunden.")
            )
            return

        # Berechtigung: Mitarbeiter ODER der Versicherungsnehmer
        customer = data["customers"].get(ticket_info.get("customer_id", ""), {})
        cust_discord_id = customer.get("discord_user_id")
        if not is_mitarbeiter(interaction) and interaction.user.id != cust_discord_id:
            await interaction.response.send_message(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Zugriff verweigert!",
                        "Nur Mitarbeiter oder der Versicherungsnehmer können das abbrechen.",
                    )
                ),
            )
            return

        # Timer zurücksetzen
        data["ticket_channels"][ch_key]["inactivity_warned_at"] = None
        data["ticket_channels"][ch_key]["last_human_message"] = get_now().isoformat()
        save_data(data)

        button.disabled = True
        button.label = "Schließen abgebrochen"
        await interaction.response.edit_message(**ev_msg(interaction.message, self))

        confirm = DEmbed(
            title="Automatisches Schließen abgebrochen",
            description=f"> {interaction.user.mention} hat das automatische Schließen abgebrochen.\n> Das Ticket bleibt geöffnet.",
            color=EMBED_COLOR,
            timestamp=get_now(),
        )
        await interaction.channel.send(**ev(confirm))


# ═══════════════════════════════════════════════════════
#   TICKET VIEWS — MODERN DESIGN
# ═══════════════════════════════════════════════════════
def get_effective_claimer_id(ticket_info: dict) -> Optional[int]:
    """
    Ermittelt den für ein Ticket zuständigen Mitarbeiter.
    - Schadensmeldung: der Mitarbeiter, der das Ticket über 'Beanspruchen' übernommen hat.
    - Kundenkontakt: der Mitarbeiter, der das Ticket eröffnet hat (kein separater
      Beanspruchen-Schritt vorhanden, daher gilt der Öffner als zuständig).
    """
    claimed_by = ticket_info.get("claimed_by")
    if claimed_by:
        return claimed_by
    if ticket_info.get("type") == "kundenkontakt":
        return ticket_info.get("opener_id")
    return None


def get_ticket_customer_member(
    guild: discord.Guild, ticket_info: dict
) -> Optional[discord.Member]:
    """Gibt das Discord-Mitglied des Kunden zurück, der zu diesem Ticket gehört."""
    customer_id = ticket_info.get("customer_id", "")
    customer = data["customers"].get(customer_id, {})
    uid = customer.get("discord_user_id")
    return guild.get_member(uid) if uid else None


class CloseRequestView(EView):
    """View für die Schließanfrage: Annehmen/Ablehnen — ausschließlich für den Kunden."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Schließen",
        style=discord.ButtonStyle.danger,
        custom_id="close_request_accept",
    )
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        ch_key = str(interaction.channel.id)
        ticket_info = data.get("ticket_channels", {}).get(ch_key)
        if not ticket_info:
            await interaction.response.send_message(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Fehler!",
                        "Ticket-Daten nicht gefunden. Bitte wende dich an einen Administrator.",
                    )
                ),
            )
            return

        customer_member = get_ticket_customer_member(interaction.guild, ticket_info)
        if not customer_member or interaction.user.id != customer_member.id:
            await interaction.response.send_message(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Zugriff verweigert!",
                        "Nur der Kunde kann diese Schließanfrage beantworten.",
                        "Kunde",
                    )
                ),
            )
            return

        for child in self.controls:
            child.disabled = True
        await interaction.response.edit_message(**ev_msg(interaction.message, self))

        add_log_entry(
            "SCHLIESSANFRAGE_ANGENOMMEN",
            interaction.user.id,
            {"channel_id": interaction.channel.id},
        )
        await close_ticket_channel(interaction, interaction.channel, ticket_info)

    @discord.ui.button(
        label="Abbrechen",
        style=discord.ButtonStyle.secondary,
        custom_id="close_request_deny",
    )
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        ch_key = str(interaction.channel.id)
        ticket_info = data.get("ticket_channels", {}).get(ch_key)
        if not ticket_info:
            await interaction.response.send_message(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Fehler!",
                        "Ticket-Daten nicht gefunden. Bitte wende dich an einen Administrator.",
                    )
                ),
            )
            return

        customer_member = get_ticket_customer_member(interaction.guild, ticket_info)
        if not customer_member or interaction.user.id != customer_member.id:
            await interaction.response.send_message(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Zugriff verweigert!",
                        "Nur der Kunde kann diese Schließanfrage beantworten.",
                        "Kunde",
                    )
                ),
            )
            return

        for child in self.controls:
            child.disabled = True
        await interaction.response.edit_message(**ev_msg(interaction.message, self))

        deny_embed = dvg_embed(
            "Schließanfrage abgelehnt!",
            f"> {interaction.user.mention} hat die Schließanfrage abgelehnt.",
        )
        await interaction.channel.send(**ev(deny_embed))
        await reenable_close_request_button(interaction.channel, ticket_info)
        add_log_entry(
            "SCHLIESSANFRAGE_ABGELEHNT",
            interaction.user.id,
            {"channel_id": interaction.channel.id},
        )


async def send_close_request(
    interaction: discord.Interaction, ticket_info: dict
) -> None:
    """Sendet eine Schließanfrage, die vom Kunden angenommen oder abgelehnt werden muss."""
    request_embed = dvg_embed(
        "Schließanfrage",
        f"> {interaction.user.mention} hat darum gebeten, dieses Ticket zu schließen.\n"
        f"> Bitte nehmen Sie die Auswahl mithilfe der untenstehenden Schaltflächen vor.",
    )
    await interaction.followup.send(**ev(request_embed, view=CloseRequestView()))

    ch_key = str(interaction.channel.id)
    if ch_key in data.get("ticket_channels", {}):
        data["ticket_channels"][ch_key][
            "close_request_panel_message_id"
        ] = interaction.message.id
        save_data(data)

    add_log_entry(
        "SCHLIESSANFRAGE_GESTELLT",
        interaction.user.id,
        {"channel_id": interaction.channel.id},
    )


async def reenable_close_request_button(
    channel: discord.abc.Messageable, ticket_info: dict
) -> None:
    """Aktiviert den Schließanfrage-Button im Ticket-Panel wieder (z.B. nach Ablehnung)."""
    panel_msg_id = ticket_info.get("close_request_panel_message_id")
    if not panel_msg_id:
        return
    try:
        panel_msg = await channel.fetch_message(panel_msg_id)
    except (discord.NotFound, discord.Forbidden):
        panel_msg = None

    if panel_msg is not None:
        if ticket_info.get("type") == "kundenkontakt":
            new_view = KundenkontaktTicketView()
        else:
            new_view = SchadensmeldungTicketView()
            claimed_by = ticket_info.get("claimed_by")
            if claimed_by:
                for child in new_view.controls:
                    if getattr(child, "custom_id", "") == "sd_claim_release":
                        child.label = "Freigeben"
                        child.style = discord.ButtonStyle.secondary
        for child in new_view.controls:
            if getattr(child, "custom_id", "") in (
                "sd_close_ticket",
                "kk_close_ticket",
            ):
                child.disabled = False
        try:
            await panel_msg.edit(**ev_msg(panel_msg, new_view))
        except discord.NotFound:
            pass

    ch_key = str(channel.id)
    if ch_key in data.get("ticket_channels", {}):
        data["ticket_channels"][ch_key].pop("close_request_panel_message_id", None)
        save_data(data)


class SchadensmeldungTicketView(EView):
    """View für Schadensmeldungs-Tickets: Beanspruchen/Freigeben + Schließanfrage."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Beanspruchen",
        style=discord.ButtonStyle.primary,
        custom_id="sd_claim_release",
    )
    async def claim_release(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        channel_key = str(interaction.channel.id)
        ticket_info = data.get("ticket_channels", {}).get(channel_key)

        if not ticket_info:
            await interaction.response.send_message(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Fehler!",
                        "Ticket-Daten nicht gefunden. Bitte wende dich an einen Administrator.",
                    )
                ),
            )
            return

        claimed_by = ticket_info.get("claimed_by")

        if claimed_by is None:
            # ── BEANSPRUCHEN ──
            if not is_mitarbeiter(interaction):
                await interaction.response.send_message(
                    ephemeral=True,
                    **ev(
                        build_error_embed(
                            "Zugriff verweigert!",
                            "Nur Mitarbeiter können Tickets beanspruchen.",
                            "Mitarbeiter",
                        )
                    ),
                )
                return

            data["ticket_channels"][channel_key]["claimed_by"] = interaction.user.id
            data["ticket_channels"][channel_key]["claimed_at"] = get_now().isoformat()
            save_data(data)

            # Sofort Buttons aktualisieren — bevor langsame API-Calls kommen
            button.label = "Freigeben"
            button.style = discord.ButtonStyle.secondary
            await interaction.response.edit_message(**ev_msg(interaction.message, self))

            # Kanalberechtigungen anpassen
            for role in _get_roles(interaction.guild, MITARBEITER_ROLE_ID):
                await interaction.channel.set_permissions(
                    role, read_messages=True, send_messages=False
                )
            await interaction.channel.set_permissions(
                interaction.user,
                read_messages=True,
                send_messages=True,
                read_message_history=True,
            )

            claim_embed = dvg_embed(
                "Ticket beansprucht!",
                f"{interaction.user.mention} hat dieses Ticket übernommen.",
            )
            await interaction.channel.send(**ev(claim_embed))
            add_log_entry(
                "TICKET_BEANSPRUCHT",
                interaction.user.id,
                {"channel_id": interaction.channel.id},
            )

        else:
            # ── FREIGEBEN ──
            if interaction.user.id != claimed_by and not is_leitungsebene(interaction):
                claimer = interaction.guild.get_member(claimed_by)
                claimer_name = claimer.mention if claimer else f"`{claimed_by}`"
                await interaction.response.send_message(
                    ephemeral=True,
                    **ev(
                        build_error_embed(
                            "Zugriff verweigert!",
                            f"Nur der Beansprucher ({claimer_name}) und die Leitungsebene können das Ticket freigeben.",
                        )
                    ),
                )
                return

            old_claimer = interaction.guild.get_member(claimed_by)
            data["ticket_channels"][channel_key]["claimed_by"] = None
            save_data(data)

            # Sofort Buttons aktualisieren
            button.label = "Beanspruchen"
            button.style = discord.ButtonStyle.primary
            await interaction.response.edit_message(**ev_msg(interaction.message, self))

            # Kanalberechtigungen wiederherstellen
            for role in _get_roles(interaction.guild, MITARBEITER_ROLE_ID):
                await interaction.channel.set_permissions(
                    role, read_messages=True, send_messages=True
                )
            if old_claimer:
                await interaction.channel.set_permissions(old_claimer, overwrite=None)

            release_embed = dvg_embed(
                "Ticket freigegeben!",
                f"{interaction.user.mention} hat das Ticket freigegeben.",
            )
            await interaction.channel.send(**ev(release_embed))
            add_log_entry(
                "TICKET_FREIGEGEBEN",
                interaction.user.id,
                {"channel_id": interaction.channel.id},
            )

    @discord.ui.button(
        label="Schließanfrage",
        style=discord.ButtonStyle.danger,
        custom_id="sd_close_ticket",
    )
    async def close_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        ch_key = str(interaction.channel.id)
        ticket_info = data.get("ticket_channels", {}).get(ch_key, {})
        claimer_id = get_effective_claimer_id(ticket_info)
        if not (
            (claimer_id is not None and interaction.user.id == claimer_id)
            or is_leitungsebene(interaction)
        ):
            await interaction.response.send_message(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Zugriff verweigert!",
                        "Nur der Mitarbeiter, der dieses Ticket beansprucht hat, oder die Leitungsebene können eine Schließanfrage stellen.",
                        "Beanspruchender Mitarbeiter / Leitungsebene",
                    )
                ),
            )
            return
        if ticket_info.get("close_request_panel_message_id"):
            await interaction.response.send_message(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Anfrage bereits gestellt!",
                        "Es liegt bereits eine offene Schließanfrage für dieses Ticket vor.",
                    )
                ),
            )
            return

        button.disabled = True
        await interaction.response.edit_message(**ev_msg(interaction.message, self))
        await send_close_request(interaction, ticket_info)


class KundenkontaktTicketView(EView):
    """View für Kundenkontakt-Tickets: Nur Schließanfrage-Button."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Schließanfrage",
        style=discord.ButtonStyle.danger,
        custom_id="kk_close_ticket",
    )
    async def close_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        ch_key = str(interaction.channel.id)
        ticket_info = data.get("ticket_channels", {}).get(ch_key, {})
        claimer_id = get_effective_claimer_id(ticket_info)
        if not (
            (claimer_id is not None and interaction.user.id == claimer_id)
            or is_leitungsebene(interaction)
        ):
            await interaction.response.send_message(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Zugriff verweigert!",
                        "Nur der Mitarbeiter, der dieses Ticket eröffnet hat, oder die Leitungsebene können eine Schließanfrage stellen.",
                        "Zuständiger Mitarbeiter / Leitungsebene",
                    )
                ),
            )
            return
        if ticket_info.get("close_request_panel_message_id"):
            await interaction.response.send_message(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Anfrage bereits gestellt!",
                        "Es liegt bereits eine offene Schließanfrage für dieses Ticket vor.",
                    )
                ),
            )
            return

        button.disabled = True
        await interaction.response.edit_message(**ev_msg(interaction.message, self))
        await send_close_request(interaction, ticket_info)


# Legacy View — bleibt für vor dem Update erstellte Tickets
class TicketCloseView(EView):
    def __init__(self, channel_id: int, customer_id: str):
        super().__init__(timeout=None)
        self.channel_id = channel_id
        self.customer_id = customer_id

    @discord.ui.button(
        label="Ticket schließen",
        style=discord.ButtonStyle.danger,
        custom_id="close_ticket",
    )
    async def close_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not is_mitarbeiter(interaction):
            await interaction.response.send_message(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
                    )
                ),
            )
            return
        ch_key = str(interaction.channel.id)
        ticket_info = data.get("ticket_channels", {}).get(
            ch_key, {"customer_id": self.customer_id}
        )
        await close_ticket_channel(interaction, interaction.channel, ticket_info)


# ═══════════════════════════════════════════════════════
#   TICKET MODALS — KUNDENKONTAKT
# ═══════════════════════════════════════════════════════
class TicketModal(discord.ui.Modal, title="Kundenkontakt-Anfrage"):
    customer_id_input = discord.ui.TextInput(
        label="Versicherungsnehmer-ID",
        placeholder="VN-XXXXXXXX",
        required=True,
        max_length=15,
    )
    reason = discord.ui.TextInput(
        label="Grund der Kontaktaufnahme",
        style=discord.TextStyle.paragraph,
        placeholder="Bitte beschreiben Sie detailliert den Anlass...",
        required=True,
        max_length=2000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            customer_id = self.customer_id_input.value.strip()
            if customer_id not in data["customers"]:
                await interaction.followup.send(
                    ephemeral=True,
                    **ev(
                        build_error_embed(
                            "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
                        )
                    ),
                )
                return
            customer = data["customers"][customer_id]

            # ── Duplikat-Check: Mitarbeiter ──
            existing_ma = get_active_ticket(interaction.user.id, "kundenkontakt")
            if existing_ma:
                await interaction.followup.send(
                    ephemeral=True,
                    **ev(
                        build_error_embed(
                            "Aktives Ticket vorhanden!",
                            f"Du hast bereits ein offenes Kundenkontakt-Ticket (<#{existing_ma}>).\nBitte schließe dieses zuerst.",
                        )
                    ),
                )
                return

            # ── Duplikat-Check: Kunde ──
            existing_cust = customer_has_active_ticket(customer_id, "kundenkontakt")
            if existing_cust:
                await interaction.followup.send(
                    ephemeral=True,
                    **ev(
                        build_error_embed(
                            "Ticket für diesen Kunden vorhanden!",
                            f"Für **{customer['rp_name']}** existiert bereits ein Kundenkontakt-Ticket (<#{existing_cust}>).",
                        )
                    ),
                )
                return

            guild = interaction.guild
            category = (
                guild.get_channel(config.get("kundenkontakt_category_id"))
                if config.get("kundenkontakt_category_id")
                else None
            )
            if not category:
                await interaction.followup.send(
                    ephemeral=True,
                    **ev(
                        build_error_embed(
                            "Nicht konfiguriert!",
                            "Kundenkontakt-Kategorie nicht eingerichtet.",
                        )
                    ),
                )
                return

            customer_user = guild.get_member(customer["discord_user_id"])
            le_roles = _get_roles(guild, LEITUNGSEBENE_ROLE_ID)
            ma_roles = _get_roles(guild, MITARBEITER_ROLE_ID)

            # Berechtigungen:
            # - Standard: kein Zugriff
            # - Leitungsebene: lesen + schreiben
            # - Öffner (Mitarbeiter): lesen + schreiben
            # - Mitarbeiter-Rolle: lesen (nicht schreiben)
            # - Kunde (Discord-User): lesen + schreiben
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False)
            }
            for le_role in le_roles:
                overwrites[le_role] = discord.PermissionOverwrite(
                    read_messages=True, send_messages=True, read_message_history=True
                )
            for ma_role in ma_roles:
                # Mitarbeiter können mitlesen, aber nicht schreiben (außer dem Öffner)
                overwrites[ma_role] = discord.PermissionOverwrite(
                    read_messages=True, send_messages=False, read_message_history=True
                )
            # Öffner bekommt write-Rechte (überschreibt die MA-Rollenregel)
            overwrites[interaction.user] = discord.PermissionOverwrite(
                read_messages=True, send_messages=True, read_message_history=True
            )
            # Kunde kann lesen und schreiben
            if customer_user:
                overwrites[customer_user] = discord.PermissionOverwrite(
                    read_messages=True, send_messages=True, read_message_history=True
                )

            ticket_channel = await category.create_text_channel(
                name=f"kontakt-{customer_id.lower()}",
                topic=f"Kundenkontakt: {customer['rp_name']} | {customer_id}",
                overwrites=overwrites,
            )

            ins_types = get_insurance_types()
            embed = DEmbed(
                title="Kundenkontakt", color=EMBED_COLOR, timestamp=get_now()
            )
            embed.add_field(
                name="Ticketinformationen",
                value=(
                    f"> <:member:1522597880437932112> `{customer['rp_name']}`\n"
                    f"> <:id:1522597735205830666> `{customer_id}`\n"
                    f"> <:datetime:1522597873286512777> `{get_now().strftime('%d.%m.%Y, %H:%M')} Uhr`\n"
                ),
                inline=False,
            )
            embed.add_field(
                name="Kontaktgrund",
                value=f"```{self.reason.value[:500]}```",
                inline=False,
            )
            ins_info = "\n".join(
                f"> <:1821serversfolder:1522597744030777405> {ins}"
                for ins in customer["versicherungen"]
            )
            embed.add_field(
                name="Versicherungsübersicht",
                value=f"{ins_info}\n> <:8558viewasrolearrow:1522597865350889472>  `{customer['total_monthly_price']:,.2f}€/Monat`",
                inline=False,
            )

            mentions = [interaction.user.mention] + (
                [customer_user.mention] if customer_user else []
            )
            await ticket_channel.send(
                **ev(embed, view=KundenkontaktTicketView(), ping=" ".join(mentions))
            )

            # ticket_channels registrieren
            data["ticket_channels"][str(ticket_channel.id)] = {
                "type": "kundenkontakt",
                "customer_id": customer_id,
                "opener_id": interaction.user.id,
                "claimed_by": None,
                "claimed_at": None,
                "opened_at": get_now().isoformat(),
                "last_human_message": get_now().isoformat(),
                "inactivity_warned_at": None,
            }
            save_data(data)

            add_log_entry(
                "TICKET_ERSTELLT",
                interaction.user.id,
                {
                    "customer_id": customer_id,
                    "channel_id": ticket_channel.id,
                    "type": "kundenkontakt",
                },
            )

            # Dokumentationskanal
            await send_to_dokumentation_channel(
                guild,
                interaction.user,
                vorgang=ticket_channel.mention,
                anliegen=f"Kundenkontakt — {self.reason.value[:200]}",
            )

            s = DEmbed(
                title="Ticket erstellt!",
                description=f"<:5975popout:1522597818127220816> {ticket_channel.mention}",
                color=EMBED_COLOR,
            )
            await interaction.followup.send(ephemeral=True, **ev(s))
        except Exception as e:
            logger.error(f"Ticket Fehler: {e}", exc_info=True)
            await interaction.followup.send(ephemeral=True, **ev_text(f"Fehler: {e}"))


# ═══════════════════════════════════════════════════════
#   TICKET MODALS — SCHADENSMELDUNG
# ═══════════════════════════════════════════════════════
class SchadensmeldungModal(discord.ui.Modal, title="Schadensmeldung einreichen"):
    customer_id_input = discord.ui.TextInput(
        label="Versicherungsnehmer-ID",
        placeholder="VN-24123456",
        required=True,
        max_length=20,
    )
    Geschädigter = discord.ui.TextInput(
        label="Geschädigter (RP-Name)",
        placeholder="Max Mustermann",
        required=True,
        max_length=100,
    )
    Täter = discord.ui.TextInput(
        label="Täter (RP-Name)", placeholder="John Doe", required=True, max_length=100
    )
    beschreibung = discord.ui.TextInput(
        label="Beschreibung des Vorfalls",
        style=discord.TextStyle.paragraph,
        placeholder="Bitte beschreiben Sie den Vorfall so detailliert wie möglich...",
        required=True,
        max_length=1000,
    )
    rechnung = discord.ui.TextInput(
        label="Rechnung/Zahlungsnachweis",
        placeholder="Rechnungsnummer oder Link",
        required=True,
        max_length=200,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            customer_id = self.customer_id_input.value.strip()
            if customer_id not in data["customers"]:
                await interaction.followup.send(
                    ephemeral=True,
                    **ev(
                        build_error_embed(
                            "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
                        )
                    ),
                )
                return
            customer = data["customers"][customer_id]

            # ── Blacklist-Check ──
            bl = blacklist_entry(customer_id)
            if bl:
                added = make_aware(datetime.fromisoformat(bl["added_at"])).strftime(
                    "%d.%m.%Y"
                )
                bl_e = dvg_embed(
                    "Einreichung abgelehnt",
                    "> Für diesen Versicherungsnehmer koennen keine Schadensmeldungen eingereicht werden.\n"
                    "> Bitte wende dich an die Leitungsebene für weitere Informationen.",
                )
                bl_e.add_field(
                    name="Kunden-ID", value=f"> `{customer_id}`", inline=True
                )
                bl_e.add_field(name="Gesperrt seit", value=f"> `{added}`", inline=True)
                await interaction.followup.send(ephemeral=True, **ev(bl_e))
                add_log_entry(
                    "BLACKLIST_BLOCK",
                    interaction.user.id,
                    {"customer_id": customer_id, "grund": bl.get("grund", "")},
                )
                return

            # ── Duplikat-Check: ein Ticket pro Kunde ──
            existing = customer_has_active_ticket(customer_id, "schadensmeldung")
            if existing:
                await interaction.followup.send(
                    ephemeral=True,
                    **ev(
                        build_error_embed(
                            "Aktive Schadensmeldung vorhanden!",
                            f"Für **{customer['rp_name']}** existiert bereits eine offene Schadensmeldung (<#{existing}>).\nBitte warte, bis diese bearbeitet wurde.",
                        )
                    ),
                )
                return

            # ── Betrugserkennung: Nachweis bereits verwendet? ──
            nachweis_val = self.rechnung.value.strip()
            duplicate = check_nachweis_duplicate(nachweis_val)
            if duplicate:
                dup_cid = duplicate.get("customer_id", "—")
                dup_date = duplicate.get("datum", "")
                dup_dt = (
                    make_aware(datetime.fromisoformat(dup_date)).strftime(
                        "%d.%m.%Y %H:%M"
                    )
                    if dup_date
                    else "—"
                )
                fraud_e = dvg_embed(
                    "Betrugsversuch erkannt!",
                    f"> Der angegebene Nachweis wurde bereits in einer früheren Schadensmeldung verwendet.\n"
                    f"> Eine erneute Einreichung mit demselben Beleg ist nicht möglich.",
                )
                fraud_e.add_field(
                    name="Nachweis", value=f"> `{nachweis_val[:100]}`", inline=False
                )
                fraud_e.add_field(
                    name="Erstmalig eingereicht am", value=f"> `{dup_dt}`", inline=True
                )
                fraud_e.add_field(
                    name="Kunden-ID (original)", value=f"> `{dup_cid}`", inline=True
                )
                await interaction.followup.send(ephemeral=True, **ev(fraud_e))
                add_log_entry(
                    "BETRUGSVERSUCH_ERKANNT",
                    interaction.user.id,
                    {
                        "nachweis": nachweis_val,
                        "customer_id": customer_id,
                        "original_customer_id": dup_cid,
                    },
                )
                return

            guild = interaction.guild
            category = (
                guild.get_channel(config.get("schadensmeldung_category_id"))
                if config.get("schadensmeldung_category_id")
                else None
            )
            if not category:
                await interaction.followup.send(
                    ephemeral=True,
                    **ev(
                        build_error_embed(
                            "Nicht konfiguriert!",
                            "Schadensmeldungs-Kategorie nicht eingerichtet.",
                        )
                    ),
                )
                return

            customer_user = guild.get_member(customer["discord_user_id"])
            le_roles = _get_roles(guild, LEITUNGSEBENE_ROLE_ID)
            ma_roles = _get_roles(guild, MITARBEITER_ROLE_ID)

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False)
            }
            for le_role in le_roles:
                overwrites[le_role] = discord.PermissionOverwrite(
                    read_messages=True, send_messages=True, read_message_history=True
                )
            for ma_role in ma_roles:
                overwrites[ma_role] = discord.PermissionOverwrite(
                    read_messages=True, send_messages=True, read_message_history=True
                )
            if customer_user:
                overwrites[customer_user] = discord.PermissionOverwrite(
                    read_messages=True, send_messages=True, read_message_history=True
                )

            ticket_channel = await category.create_text_channel(
                name=f"schaden-{customer_id.lower()}",
                topic=f"Schadensmeldung: {customer['rp_name']} | {customer_id}",
                overwrites=overwrites,
            )

            embed = dvg_embed("Schadensmeldung")
            embed.add_field(
                name="Fallinformationen",
                value=(
                    f"> <:member:1522597880437932112> `{customer['rp_name']}`\n"
                    f"> <:id:1522597735205830666> `{customer_id}`\n"
                    f"> <:datetime:1522597873286512777> `{get_now().strftime('%d.%m.%Y, %H:%M Uhr')}`"
                ),
                inline=False,
            )
            embed.add_field(
                name="Beteiligte Personen",
                value=f"> <:opfer:1522597868278644817> `{self.Geschädigter.value}`\n> <:taeter:1522597859109900328> `{self.Täter.value}`",
                inline=False,
            )
            embed.add_field(
                name="Vorfallbeschreibung",
                value=f"```{self.beschreibung.value}```",
                inline=False,
            )
            embed.add_field(
                name="Nachweis (Rechnung)",
                value=f"> <:7896pinned:1522597854223274065> `{nachweis_val}`",
                inline=False,
            )

            ma_ping = " ".join(r.mention for r in ma_roles) if ma_roles else ""
            await ticket_channel.send(
                **ev(
                    embed,
                    view=SchadensmeldungTicketView(),
                    ping=f"{ma_ping} — Neue Schadensmeldung!",
                )
            )

            jetzt = get_now().isoformat()

            # ticket_channels registrieren
            data["ticket_channels"][str(ticket_channel.id)] = {
                "type": "schadensmeldung",
                "customer_id": customer_id,
                "opener_id": interaction.user.id,
                "claimed_by": None,
                "claimed_at": None,
                "opened_at": jetzt,
                "last_human_message": jetzt,
                "inactivity_warned_at": None,
            }

            # Schadenhistorie anlegen
            schaden_id = generate_schaden_id()
            data.setdefault("schaden_historie", {}).setdefault(customer_id, []).append(
                {
                    "id": schaden_id,
                    "datum": jetzt,
                    "Geschädigter": self.Geschädigter.value,
                    "Täter": self.Täter.value,
                    "nachweis": nachweis_val,
                    "beschreibung": self.beschreibung.value[:500],
                    "status": "offen",
                    "kanal_id": ticket_channel.id,
                    "closed_at": None,
                    "closed_by": None,
                }
            )
            save_data(data)

            add_log_entry(
                "TICKET_ERSTELLT",
                interaction.user.id,
                {
                    "customer_id": customer_id,
                    "channel_id": ticket_channel.id,
                    "type": "schadensmeldung",
                },
            )
            await send_to_dokumentation_channel(
                guild,
                interaction.user,
                vorgang=ticket_channel.mention,
                anliegen=f"Schadensmeldung — Geschädigter: {self.Geschädigter.value} | Täter: {self.Täter.value}",
            )

            s = dvg_embed(
                "Schadensmeldung eingereicht!",
                f" <:5975popout:1522597818127220816> {ticket_channel.mention}",
            )
            await interaction.followup.send(ephemeral=True, **ev(s))
        except Exception as e:
            logger.error(f"Schadensmeldung Fehler: {e}")
            await interaction.followup.send(ephemeral=True, **ev_text(f"Fehler: {e}"))


# ═══════════════════════════════════════════════════════
#   TICKET BEFEHLE — ADD / REMOVE
# ═══════════════════════════════════════════════════════
@bot.tree.command(name="add", description="Fügt eine Person zum aktuellen Ticket hinzu")
@app_commands.describe(user="Der User, der hinzugefügt werden soll")
async def add_user_to_ticket(interaction: discord.Interaction, user: discord.Member):
    if not is_mitarbeiter(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
                )
            ),
        )
        return
    if not (
        interaction.channel.name.startswith("kontakt-")
        or interaction.channel.name.startswith("schaden-")
    ):
        await interaction.response.send_message(
            ephemeral=True, **ev_text(" Nur in Ticket-Channels nutzbar.")
        )
        return
    await interaction.channel.set_permissions(
        user, read_messages=True, send_messages=True, read_message_history=True
    )
    e = DEmbed(
        title="Person hinzugefügt!",
        description=f"{interaction.user.mention} hat {user.mention} zu Ticket hinzugefügt.",
        color=EMBED_COLOR,
    )
    await interaction.response.send_message(**ev(e))


@bot.tree.command(
    name="remove", description="Entfernt eine Person vom aktuellen Ticket"
)
@app_commands.describe(user="Der User, der entfernt werden soll")
async def remove_user_from_ticket(
    interaction: discord.Interaction, user: discord.Member
):
    if not is_mitarbeiter(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
                )
            ),
        )
        return
    if not (
        interaction.channel.name.startswith("kontakt-")
        or interaction.channel.name.startswith("schaden-")
    ):
        await interaction.response.send_message(
            ephemeral=True, **ev_text(" Nur in Ticket-Channels nutzbar.")
        )
        return
    await interaction.channel.set_permissions(user, overwrite=None)
    e = DEmbed(
        title="Person entfernt!",
        description=f"{interaction.user.mention} hat {user.mention} vom Ticket entfernt.",
        color=EMBED_COLOR,
    )
    await interaction.response.send_message(**ev(e))


# ═══════════════════════════════════════════════════════
#   LOGS ANZEIGEN
# ═══════════════════════════════════════════════════════
@bot.tree.command(
    name="logs-anzeigen", description="Zeigt die letzten Bot-Aktivitäten an"
)
@app_commands.describe(anzahl="Anzahl der anzuzeigenden Log-Einträge (Standard: 10)")
async def show_logs(interaction: discord.Interaction, anzahl: int = 10):
    if not is_leitungsebene(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!", "Nur die Leitungsebene.", "Leitungsebene"
                )
            ),
        )
        return
    await interaction.response.defer(ephemeral=True)
    try:
        if not data["logs"]:
            await interaction.followup.send(
                ephemeral=True, **ev(dvg_embed("Keine Logs vorhanden!"))
            )
            return
        anzahl = max(1, min(anzahl, 25))
        recent = list(reversed(data["logs"][-anzahl:]))
        action_map = {
            "KUNDENAKTE_ERSTELLT": ("", "Kundenakte erstellt"),
            "RECHNUNG_ERSTELLT": ("", "Rechnung ausgestellt"),
            "RECHNUNG_ARCHIVIERT": ("", "Rechnung archiviert"),
            "MAHNUNG_1": ("", "1. Mahnung"),
            "MAHNUNG_2": ("", "2. Mahnung (+5%)"),
            "MAHNUNG_3": ("", "3. Mahnung (+10%)"),
            "TICKET_ERSTELLT": ("", "Ticket erstellt"),
            "TICKET_GESCHLOSSEN": ("", "Ticket geschlossen"),
            "TICKET_BEANSPRUCHT": ("", "Ticket beansprucht"),
            "TICKET_FREIGEGEBEN": ("", "Ticket freigegeben"),
            "AKTE_ARCHIVIERT": ("", "Akte archiviert"),
            "AUSZAHLUNG_EINGEREICHT": ("", "Auszahlungsantrag"),
            "AUSZAHLUNG_BESTAETIGT": ("", "Auszahlung bestätigt"),
            "AUSZAHLUNG_ABGELEHNT": ("", "Auszahlung abgelehnt"),
            "VERSICHERUNG_NACHGEBUCHT": ("", "Versicherung nachgebucht"),
            "VERSICHERUNG_GEKUENDIGT": ("", "Versicherung gekündigt"),
        }
        embed = DEmbed(
            title="Aktivitätsprotokoll",
            description=f"**Letzte {len(recent)} Aktivitäten**",
            color=EMBED_COLOR,
            timestamp=get_now(),
        )
        for log in recent:
            ts = make_aware(datetime.fromisoformat(log["timestamp"])).strftime(
                "%d.%m.%Y, %H:%M Uhr"
            )
            user = (
                interaction.guild.get_member(log["user_id"])
                if log.get("user_id") and log["user_id"] != 0
                else None
            )
            user_name = user.mention if user else "System System"
            emoji, display = action_map.get(log["action"], ("", log["action"]))
            details = log.get("details", {})
            parts = []
            if "customer_id" in details:
                parts.append(f"Kunden-ID: `{details['customer_id']}`")
            if "invoice_id" in details:
                parts.append(f"Rechnung: `{details['invoice_id']}`")
            detail_str = "\n".join(f"> {p}" for p in parts[:3]) if parts else "> `-`"
            embed.add_field(
                name=f"{emoji} {display}",
                value=f"> **{ts}**\n> {user_name}\n{detail_str}",
                inline=False,
            )
        await interaction.followup.send(ephemeral=True, **ev(embed))
    except Exception as e:
        logger.error(f"Logs Fehler: {e}", exc_info=True)
        await interaction.followup.send(
            ephemeral=True, **ev(build_error_embed("Fehler!", str(e)))
        )


# ═══════════════════════════════════════════════════════
#   AKTE ANZEIGEN
# ═══════════════════════════════════════════════════════
@bot.tree.command(
    name="akte-anzeigen",
    description="Zeigt die eigene Versicherungsakte oder die eines Kunden (Mitarbeiter)",
)
@app_commands.describe(
    customer_id="Versicherungsnehmer-ID (nur für Mitarbeiter; Kunden leer lassen)"
)
@app_commands.autocomplete(customer_id=customer_id_all_autocomplete)
async def show_customer(
    interaction: discord.Interaction, customer_id: Optional[str] = None
):
    mitarbeiter = is_mitarbeiter(interaction)
    if not mitarbeiter:
        found_id = next(
            (
                cid
                for cid, c in data["customers"].items()
                if c.get("discord_user_id") == interaction.user.id
                and c.get("status") == "aktiv"
            ),
            None,
        )
        if not found_id:
            await interaction.response.send_message(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Keine Akte gefunden!",
                        "Für Ihren Account wurde keine aktive Versicherungsakte gefunden.\nBitte wenden Sie sich an einen Mitarbeiter.",
                    )
                ),
            )
            return
        customer_id = found_id
    else:
        if not customer_id:
            await interaction.response.send_message(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Fehlende Angabe!",
                        "Bitte geben Sie eine Versicherungsnehmer-ID an.",
                    )
                ),
            )
            return
        if customer_id not in data["customers"]:
            await interaction.response.send_message(
                ephemeral=True,
                **ev(
                    build_error_embed(
                        "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
                    )
                ),
            )
            return

    customer = data["customers"][customer_id]
    ins_types = get_insurance_types()
    embed = DEmbed(
        title=f" Kundenakte — {customer['rp_name']}",
        color=EMBED_COLOR,
        timestamp=get_now(),
    )
    embed.add_field(
        name="Stammdaten",
        value=f"> <:member:1522597880437932112> `{customer['rp_name']}`\n> <:id:1522597735205830666> `{customer_id}`\n> <:hbpay:1522597775647178905> `{customer['hbpay_nummer']}`",
        inline=False,
    )

    auszahlungen = customer.get("auszahlungen", {})
    ins_text = ""
    for ins in customer.get("versicherungen", []):
        limit = ins_types.get(ins, {}).get("auszahlung_limit", 0.0)
        ausgezahlt = auszahlungen.get(ins, 0.0)
        bar_filled = int((ausgezahlt / limit * 10)) if limit > 0 else 0
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        ins_text += f"> **{ins}**\n> `{bar}` {ausgezahlt:,.0f}€ / {limit:,.0f}€\n"
    embed.add_field(
        name="Versicherungen & Auszahlungslimits",
        value=ins_text or "> Keine",
        inline=False,
    )

    off_re = len(
        [
            inv
            for inv in data["invoices"].values()
            if inv["customer_id"] == customer_id and not inv.get("paid")
        ]
    )
    bez_re = len(
        [
            inv
            for inv in data["invoices"].values()
            if inv["customer_id"] == customer_id and inv.get("paid")
        ]
    )
    embed.add_field(
        name="Rechnungsübersicht",
        value=f"> <a:ausstehend:1522597723872952461> `{off_re}`\n> <:archiviert:1522597781557219448> `{bez_re}`\n> <:6509addguild:1522597829917413396> `{customer['total_monthly_price']:,.2f}€`",
        inline=False,
    )
    thread_id = customer.get("thread_id")
    if thread_id:
        embed.add_field(
            name="Versicherungsakte",
            value=f"> <:8312activethreads:1522597862779785276> <#{thread_id}>",
            inline=False,
        )

    embed.add_field(
        name="Systemdaten (Erstellung)",
        value=f"> <:datetime:1522597873286512777> {make_aware(datetime.fromisoformat(customer['created_at'])).strftime('%d.%m.%Y, %H:%M Uhr')}\n> <:mitarbeiter:1522597807352057928> <@{customer['discord_user_id']}>",
        inline=False,
    )
    await interaction.response.send_message(
        ephemeral=True, **ev(embed, ping=f"<@{customer['discord_user_id']}>")
    )


# ═══════════════════════════════════════════════════════
#   STATISTIKEN
# ═══════════════════════════════════════════════════════
@bot.tree.command(
    name="statistiken", description="Zeigt eine Übersicht aller Bot-Statistiken"
)
async def show_stats(interaction: discord.Interaction):
    if not is_leitungsebene(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!", "Nur die Leitungsebene.", "Leitungsebene"
                )
            ),
        )
        return
    customers = data.get("customers", {})
    invoices = data.get("invoices", {})
    pending_az = data.get("pending_auszahlungen", {})
    tickets = data.get("ticket_channels", {})
    aktive = sum(1 for c in customers.values() if c.get("status") == "aktiv")
    archiviert = sum(1 for c in customers.values() if c.get("status") == "archiviert")
    off_re = sum(1 for inv in invoices.values() if not inv.get("paid"))
    bez_re = sum(1 for inv in invoices.values() if inv.get("paid"))
    aus_pend = sum(1 for az in pending_az.values() if az.get("status") == "ausstehend")
    aus_best = sum(1 for az in pending_az.values() if az.get("status") == "bestätigt")
    offene_sm = sum(1 for t in tickets.values() if t.get("type") == "schadensmeldung")
    offene_kk = sum(1 for t in tickets.values() if t.get("type") == "kundenkontakt")
    claimed = sum(1 for t in tickets.values() if t.get("claimed_by") is not None)
    total_mb = sum(
        c.get("total_monthly_price", 0)
        for c in customers.values()
        if c.get("status") == "aktiv"
    )
    total_az = sum(sum(c.get("auszahlungen", {}).values()) for c in customers.values())
    vc = {}
    for c in customers.values():
        if c.get("status") == "aktiv":
            for ins in c.get("versicherungen", []):
                vc[ins] = vc.get(ins, 0) + 1
    beliebteste = max(vc, key=vc.get) if vc else "—"
    embed = dvg_embed("InsuranceGuard v4 — Statistiken")
    embed.add_field(
        name="Kundenstamm",
        value=f"> Aktiv: **`{aktive}`**\n> Archiviert: `{archiviert}`\n> Gesamt: `{len(customers)}`",
        inline=True,
    )
    embed.add_field(
        name="Finanzen",
        value=f"> Monatsbeiträge: **`{total_mb:,.2f}€`**\n> Ausgezahlt: `{total_az:,.2f}€`",
        inline=True,
    )
    embed.add_field(
        name="Rechnungen",
        value=f"> Offen: **`{off_re}`**\n> Bezahlt: `{bez_re}`",
        inline=True,
    )
    # ── Bearbeitungszeiten ───────────────────────────────────────────────────
    stats_list = data.get("ticket_stats", [])
    sm_stats = [
        s
        for s in stats_list
        if s.get("type") == "schadensmeldung" and s.get("duration_minutes")
    ]
    kk_stats = [
        s
        for s in stats_list
        if s.get("type") == "kundenkontakt" and s.get("duration_minutes")
    ]

    def avg_min(lst):
        return int(sum(s["duration_minutes"] for s in lst) / len(lst)) if lst else None

    def fmt_min(m):
        return f"{m // 60}h {m % 60}min" if m else "—"

    embed.add_field(
        name="Bearbeitungszeiten",
        value=(
            f"> Schadensmeldung Ø: `{fmt_min(avg_min(sm_stats))}`  ({len(sm_stats)} abgeschlossen)\n"
            f"> Kundenkontakt Ø: `{fmt_min(avg_min(kk_stats))}`  ({len(kk_stats)} abgeschlossen)"
        ),
        inline=False,
    )
    await interaction.response.send_message(ephemeral=True, **ev(embed))


# ═══════════════════════════════════════════════════════
#   SCHADENHISTORIE
# ═══════════════════════════════════════════════════════
@bot.tree.command(
    name="schaden-historie",
    description="Zeigt die Schadenhistorie eines Versicherungsnehmers",
)
@app_commands.describe(customer_id="Versicherungsnehmer-ID")
@app_commands.autocomplete(customer_id=customer_id_autocomplete)
async def cmd_schaden_historie(interaction: discord.Interaction, customer_id: str):
    if not is_mitarbeiter(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
                )
            ),
        )
        return
    if customer_id not in data["customers"]:
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
                )
            ),
        )
        return

    customer = data["customers"][customer_id]
    history = data.get("schaden_historie", {}).get(customer_id, [])

    e = dvg_embed(
        f"Schadenhistorie — {customer['rp_name']}",
        f"> Kunden-ID: `{customer_id}`\n> Gesamt: **{len(history)}** Schadenfall/Schadenfälle",
    )

    if not history:
        e.add_field(
            name="Keine Einträge",
            value="> Für diesen Kunden wurden noch keine Schadensmeldungen eingereicht.",
            inline=False,
        )
    else:
        for entry in sorted(history, key=lambda x: x.get("datum", ""), reverse=True)[
            :10
        ]:
            datum = (
                make_aware(datetime.fromisoformat(entry["datum"])).strftime(
                    "%d.%m.%Y %H:%M"
                )
                if entry.get("datum")
                else "—"
            )
            status = (
                " Abgeschlossen" if entry.get("status") == "abgeschlossen" else " Offen"
            )
            closed_dt = ""
            if entry.get("closed_at"):
                closed_dt = f"\n> Abgeschlossen: `{make_aware(datetime.fromisoformat(entry['closed_at'])).strftime('%d.%m.%Y %H:%M')}`"
            e.add_field(
                name=f"`{entry.get('id', '—')}` — {datum}",
                value=(
                    f"> Status: {status}\n"
                    f"> Geschädigter: **{entry.get('Geschädigter', '—')}**\n"
                    f"> Täter: **{entry.get('Täter', '—')}**\n"
                    f"> Nachweis: `{entry.get('nachweis', '—')[:60]}`" + closed_dt
                ),
                inline=False,
            )

    if len(history) > 10:
        e.add_field(
            name="Hinweis",
            value=f"> Zeige die letzten 10 von {len(history)} Einträgen.",
            inline=False,
        )

    await interaction.response.send_message(ephemeral=True, **ev(e))


# ═══════════════════════════════════════════════════════
#   PANEL-AKTUALISIEREN (manueller Trigger)
# ═══════════════════════════════════════════════════════
@bot.tree.command(
    name="panel-aktualisieren",
    description="[Admin] Aktualisiert die Bearbeitungszeit im Schadensmeldungs-Panel sofort",
)
async def cmd_panel_aktualisieren(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!", "Nur Administratoren.", "Administrator"
                )
            ),
        )
        return
    await interaction.response.defer(ephemeral=True)
    ok = await _do_panel_refresh()
    if ok:
        e = dvg_embed(
            "Panel aktualisiert",
            "> Die Bearbeitungszeit im Schadensmeldungs-Panel wurde erfolgreich aktualisiert.",
        )
    else:
        e = dvg_embed(
            "Panel nicht gefunden",
            "> Das Panel konnte nicht aktualisiert werden.\n"
            "> Mögliche Ursachen:\n"
            "> `-` Kein Panel-Kanal konfiguriert (`/einstellung-kanaele`)\n"
            "> `-` Die Bot-Nachricht wurde gelöscht oder ist nicht mehr auffindbar\n"
            "> `-` Bitte Panel neu posten mit `/einstellung-kanaele`",
        )
    await interaction.followup.send(ephemeral=True, **ev(e))


# ═══════════════════════════════════════════════════════
#   BLACKLIST
# ═══════════════════════════════════════════════════════
@bot.tree.command(
    name="blacklist-add", description="[LE] Sperrt einen Kunden von Schadensmeldungen"
)
@app_commands.describe(
    customer_id="Versicherungsnehmer-ID", grund="Grund für die Sperrung"
)
@app_commands.autocomplete(customer_id=customer_id_autocomplete)
async def cmd_blacklist_add(
    interaction: discord.Interaction, customer_id: str, grund: str
):
    if not is_leitungsebene(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!", "Nur die Leitungsebene.", "Leitungsebene"
                )
            ),
        )
        return
    if customer_id not in data["customers"]:
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
                )
            ),
        )
        return
    if is_blacklisted(customer_id):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                dvg_embed(
                    "Bereits gesperrt",
                    f"> Kunden-ID `{customer_id}` ist bereits auf der Blacklist.",
                )
            ),
        )
        return

    data["blacklist"][customer_id] = {
        "grund": grund,
        "added_by": interaction.user.id,
        "added_at": get_now().isoformat(),
    }
    save_data(data)

    customer = data["customers"][customer_id]
    e = dvg_embed(
        "Kunde zur Blacklist hinzugefuegt",
        f"> **{customer['rp_name']}** (`{customer_id}`) wurde gesperrt.",
    )
    e.add_field(name="Grund", value=f"> {grund}", inline=False)
    e.add_field(name="Gesperrt von", value=f"> {interaction.user.mention}", inline=True)
    e.add_field(
        name="Datum", value=f"> `{get_now().strftime('%d.%m.%Y %H:%M')}`", inline=True
    )
    await interaction.response.send_message(ephemeral=True, **ev(e))
    await send_to_log_channel(interaction.guild, e)
    add_log_entry(
        "BLACKLIST_ADD",
        interaction.user.id,
        {"customer_id": customer_id, "grund": grund},
    )


@bot.tree.command(
    name="blacklist-remove", description="[LE] Hebt die Sperrung eines Kunden auf"
)
@app_commands.describe(customer_id="Versicherungsnehmer-ID")
@app_commands.autocomplete(customer_id=customer_id_all_autocomplete)
async def cmd_blacklist_remove(interaction: discord.Interaction, customer_id: str):
    if not is_leitungsebene(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!", "Nur die Leitungsebene.", "Leitungsebene"
                )
            ),
        )
        return
    if not is_blacklisted(customer_id):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                dvg_embed(
                    "Nicht gesperrt", f"> `{customer_id}` ist nicht auf der Blacklist."
                )
            ),
        )
        return

    entry = data["blacklist"].pop(customer_id)
    save_data(data)
    customer = data["customers"].get(customer_id, {})
    e = dvg_embed(
        "Sperrung aufgehoben",
        f"> **{customer.get('rp_name', customer_id)}** (`{customer_id}`) wurde entsperrt.",
    )
    e.add_field(
        name="Ursprünglicher Grund", value=f"> {entry.get('grund', '—')}", inline=False
    )
    e.add_field(
        name="Aufgehoben von", value=f"> {interaction.user.mention}", inline=True
    )
    await interaction.response.send_message(ephemeral=True, **ev(e))
    await send_to_log_channel(interaction.guild, e)
    add_log_entry("BLACKLIST_REMOVE", interaction.user.id, {"customer_id": customer_id})


@bot.tree.command(name="blacklist-liste", description="Zeigt alle gesperrten Kunden")
async def cmd_blacklist_liste(interaction: discord.Interaction):
    if not is_mitarbeiter(interaction):
        await interaction.response.send_message(
            ephemeral=True,
            **ev(
                build_error_embed(
                    "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
                )
            ),
        )
        return
    bl = data.get("blacklist", {})
    e = dvg_embed("Blacklist", f"> {len(bl)} gesperrte Kunden")
    if not bl:
        e.add_field(name="Einträge", value="> Keine Kunden gesperrt.", inline=False)
    else:
        for cid, entry in list(bl.items())[:20]:
            cust = data["customers"].get(cid, {})
            added = (
                make_aware(datetime.fromisoformat(entry["added_at"])).strftime(
                    "%d.%m.%Y"
                )
                if entry.get("added_at")
                else "—"
            )
            adder = interaction.guild.get_member(entry.get("added_by", 0))
            e.add_field(
                name=f"{cust.get('rp_name', 'Unbekannt')} — `{cid}`",
                value=(
                    f"> <:taeter:1522597859109900328>  {entry.get('grund', '*N/A*')}\n"
                    f"> <:3156editsecurityactions:1522597767359496202> `{added}` von {adder.mention if adder else '*N/A*'}"
                ),
                inline=False,
            )
    await interaction.response.send_message(ephemeral=True, **ev(e))


# ═══════════════════════════════════════════════════════
#   AUTOMATISCHE TASKS
# ═══════════════════════════════════════════════════════
@tasks.loop(hours=24)
async def check_invoices():
    try:
        now = get_now()
        for invoice_id, inv in list(data["invoices"].items()):
            if inv.get("paid", False):
                continue
            try:
                due_date = make_aware(datetime.fromisoformat(inv["due_date"]))
            except Exception:
                continue

            days_until = (due_date - now).days  # negativ = überfällig
            days_overdue = (now - due_date).days

            # ── DM-Erinnerung 24h vor Fälligkeit ────────────────────────────
            if days_until == 1 and not inv.get("dm_reminder_sent", False):
                for guild in bot.guilds:
                    await send_invoice_due_dm(guild, invoice_id, inv)
                    break

            if days_overdue < 0:
                continue

            rc = inv.get("reminder_count", 0)
            if days_overdue == 0 and rc == 0:
                await send_reminder(invoice_id, inv, 1, 0)
                data["invoices"][invoice_id]["reminder_count"] = 1
                save_data(data)
            elif days_overdue == 1 and rc == 1:
                data["invoices"][invoice_id]["betrag"] = inv["original_betrag"] * 1.05
                await send_reminder(invoice_id, data["invoices"][invoice_id], 2, 5)
                data["invoices"][invoice_id]["reminder_count"] = 2
                save_data(data)
            elif days_overdue == 2 and rc == 2:
                data["invoices"][invoice_id]["betrag"] = inv["original_betrag"] * 1.10
                await send_reminder(invoice_id, data["invoices"][invoice_id], 3, 10)
                data["invoices"][invoice_id]["reminder_count"] = 3
                save_data(data)
    except Exception as e:
        logger.error(f"Mahnungsprüfung Fehler: {e}", exc_info=True)


@tasks.loop(hours=24)
async def auto_backup():
    try:
        if not config.get("log_channel_id"):
            return
        ts = get_now().strftime("%Y%m%d_%H%M%S")
        e = dvg_embed("Automatisches Datenbank-Backup")
        e.add_field(
            name="Information",
            value="> Alle `24 Stunden` werden die Daten gesichert.",
            inline=False,
        )
        e.add_field(
            name="Enthaltene Dateien",
            value="> <:1821serversfolder:1522597744030777405> `insurance_data.json`\n> <:1821serversfolder:1522597744030777405> `bot_config.json`",
            inline=False,
        )
        e.add_field(
            name="Zeitstempel",
            value=f"> {get_now().strftime('%d.%m.%Y, %H:%M:%S Uhr')}",
            inline=False,
        )
        for guild in bot.guilds:
            ch = guild.get_channel(config["log_channel_id"])
            if ch:
                buf = create_zip_buffer()
                file = discord.File(buf, filename=f"auto_backup_{ts}.zip")
                await ch.send(file=file, **ev(e, file=file.filename))
                break
    except Exception as ex:
        logger.error(f"Auto-Backup Fehler: {ex}", exc_info=True)


@tasks.loop(hours=6)
async def refresh_schadensmeldung_panel():
    """
    Aktualisiert die Bearbeitungszeit im Schadensmeldungs-Panel alle 6 Stunden.
    Erstellt das Feld wenn es noch nicht im Panel vorhanden ist.
    """
    await _do_panel_refresh()


def build_schadensmeldung_panel_embed() -> DEmbed:
    """Panel-Inhalt für das Schadensmeldungs-Panel (inkl. aktueller Bearbeitungszeit)."""
    embed_sm = dvg_embed(
        "Schadensmeldung",
        "Liebe Versicherungsnehmer:innen,\n> hier können sie Schadensmeldungen einreichen.",
    )
    embed_sm.add_field(
        name="Wie funktioniert das System?",
        value="> 1. Klicken Sie auf den Button unten!\n> 2. Geben Sie Ihre Kunden-ID ein!\n> 3. Füllen Sie das Formular aus!\n> 4. Ein Schadensfall-Ticket wird erstellt!",
        inline=False,
    )
    embed_sm.add_field(
        name="Welche Angaben sind erforderlich?",
        value="> `-` **Kunden-ID**\n> `-` **Geschädigter** (RP-Name)\n> `-` **Täter** (RP-Name)\n> `-` **Vorfallbeschreibung**\n> `-` **Rechnung/Nachweis**",
        inline=False,
    )
    # Voraussichtliche Bearbeitungszeit aus ticket_stats berechnen
    sm_stats = [
        s
        for s in data.get("ticket_stats", [])
        if s.get("type") == "schadensmeldung" and s.get("duration_minutes")
    ]
    if sm_stats:
        avg_m = int(sum(s["duration_minutes"] for s in sm_stats) / len(sm_stats))
        h, m = divmod(avg_m, 60)
        avg_tx = f"`{h}h {m}min`" if h else f"`{m} Minuten`"
        bearbzeit = f"> Voraussichtliche Bearbeitungszeit: {avg_tx}\n> Basierend auf {len(sm_stats)} abgeschlossenen Vorgängen."
    else:
        bearbzeit = "> Voraussichtliche Bearbeitungszeit: *N/A*"
    embed_sm.add_field(name="Bearbeitungszeit", value=bearbzeit, inline=False)
    embed_sm.big = True
    return embed_sm


async def _do_panel_refresh() -> bool:
    """
    Kernlogik für den Panel-Refresh — separat aufrufbar (Command + Task).
    Baut das Schadensmeldungs-Panel mit aktueller Bearbeitungszeit neu auf.
    Gibt True zurück wenn das Panel erfolgreich aktualisiert wurde.
    """
    try:
        sm_ch_id = config.get("schadensmeldung_channel_id")
        if not sm_ch_id:
            return False
        for guild in bot.guilds:
            ch = guild.get_channel(sm_ch_id)
            if not ch:
                continue
            async for msg in ch.history(limit=30):
                if msg.author.id != bot.user.id:
                    continue
                if "open_schadensmeldung" not in message_custom_ids(msg):
                    continue
                await msg.edit(
                    **v2_edit(
                        msg, build_schadensmeldung_panel_embed(), SchadensmeldungView()
                    )
                )
                logger.info("Schadensmeldungs-Panel aktualisiert")
                return True
            break
    except Exception as ex:
        logger.error(f"Panel-Refresh Fehler: {ex}", exc_info=True)
    return False


# ═══════════════════════════════════════════════════════
#   ON_MESSAGE — Aktivitätstracking für Inaktivitätswarnung
# ═══════════════════════════════════════════════════════
@bot.event
async def on_message(message: discord.Message):
    """Aktualisiert last_human_message für Ticket-Channels bei menschlicher Aktivität."""
    if message.author.bot:
        await bot.process_commands(message)
        return
    ch_key = str(message.channel.id)
    if ch_key in data.get("ticket_channels", {}):
        data["ticket_channels"][ch_key]["last_human_message"] = get_now().isoformat()
        data["ticket_channels"][ch_key][
            "inactivity_warned_at"
        ] = None  # Timer zurücksetzen
        save_data(data)
    await bot.process_commands(message)


# ═══════════════════════════════════════════════════════
#   INAKTIVITÄTS-TASK (alle 30 Minuten)
# ═══════════════════════════════════════════════════════
@tasks.loop(minutes=30)
async def check_ticket_inactivity():
    """
    Prüft alle offenen Tickets auf Inaktivität:
    - >= 16h ohne menschliche Nachricht: Warnung senden
    - >= 24h ohne menschliche Nachricht: Auto-Close
    """
    now = get_now()
    for ch_id_str, info in list(data.get("ticket_channels", {}).items()):
        last_human = info.get("last_human_message")
        warned_at = info.get("inactivity_warned_at")

        if not last_human:
            continue

        try:
            last_dt = make_aware(datetime.fromisoformat(last_human))
        except Exception:
            continue

        hours_inactive = (now - last_dt).total_seconds() / 3600

        if warned_at and hours_inactive >= 24.0:
            for guild in bot.guilds:
                channel = guild.get_channel(int(ch_id_str))
                if channel:
                    await _auto_close_ticket(guild, ch_id_str, info)
                    break
            else:
                data["ticket_channels"].pop(ch_id_str, None)
                save_data(data)

        elif not warned_at and hours_inactive >= 16.0:
            for guild in bot.guilds:
                channel = guild.get_channel(int(ch_id_str))
                if channel:
                    await _send_inactivity_warning(channel, ch_id_str, info)
                    break


@check_ticket_inactivity.before_loop
async def _before_inactivity():
    """5 Minuten Wartezeit nach Neustart — verhindert Fehlalarme bei alten Tickets."""
    await bot.wait_until_ready()
    await asyncio.sleep(300)


# ═══════════════════════════════════════════════════════
#   HEALTH-CHECK (Render.com) — kein Dashboard, keine Webseite
# ═══════════════════════════════════════════════════════
class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"InsuranceGuard v4 laeuft!"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # Konsole sauber halten
        pass


def keep_alive():
    """
    Startet nur dann einen winzigen Health-Check-Server, wenn der Host einen
    offenen Port erwartet (Umgebungsvariable PORT, z. B. Render Web Service).
    Es gibt keine Webseite, kein Portal und keine Transcript-Links mehr.
    """
    port = os.environ.get("PORT")
    if not port:
        return
    server = HTTPServer(("0.0.0.0", int(port)), _HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


# ═══════════════════════════════════════════════════════
#   MAIN
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    keep_alive()
    token = os.getenv("INSURANCE_TOKEN")
    if not token:
        logger.error(
            "INSURANCE_TOKEN nicht gefunden! Bitte als Umgebungsvariable setzen."
        )
    else:
        logger.info("InsuranceGuard v4 wird gestartet...")
        bot.run(token)
