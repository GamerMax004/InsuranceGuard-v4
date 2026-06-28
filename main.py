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

# Transcript-Verzeichnis anlegen (für Online-Dashboard)
# Umgebungsvariable BOT_BASE_URL auf die öffentliche Render-URL setzen,
# z.B. https://insuranceguard.onrender.com → Links werden dann generiert
os.makedirs("transcripts", exist_ok=True)
BOT_BASE_URL = os.environ.get("BOT_BASE_URL", "").rstrip("/")

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
        "Berufsunfähigkeitsversicherung": {
            "price": 10000.00,
            "role": "Berufsunfähigkeitsversicherung",
            "auszahlung_limit": 20000.00,
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
#  Invisible-Border-Farbe: entspricht exakt dem Discord-Embed-Hintergrund
#  (#2B2D31 Dark Mode) → der farbige Streifen links ist optisch nicht sichtbar.
#  Alle visuellen Unterschiede kommen aus Titel, Beschreibung und Struktur.
EMBED_COLOR = 0x393A41
EMBED_ERROR = 0xC03A2B
EMBED_WARNING = 0xE67E22
EMBED_SUCCESS = 0x27AE5F

# Legacy-Aliase (werden intern nicht mehr direkt genutzt, aber falls externe
# Referenzen bestehen bleiben sie vorhanden)
COLOR_PRIMARY = EMBED_COLOR
COLOR_SUCCESS = EMBED_SUCCESS
COLOR_WARNING = EMBED_WARNING
COLOR_ERROR = EMBED_ERROR
COLOR_INFO = EMBED_COLOR
COLOR_DAMAGE = EMBED_COLOR
COLOR_CLAIM = EMBED_COLOR

# DVG-Akzentfarben (für spätere Nutzung in Visualisierungen)
DVG_BLUE = 0x3D4EC5
DVG_RED = 0xB82238
DVG_PURPLE = 0x5A3D8A

# Tuple mit Role-IDs für Multi-Server-Support
MITARBEITER_ROLE_ID = (1408800823571513537, 1495094890298871874)
LEITUNGSEBENE_ROLE_ID = (1408797319134187601, 1495094890307256559)
FIRMENKONTOROLLE_ROLE_ID = (1474047313025433684, 1495094890323906564)
KUNDEN_ROLE_NAME = "Versicherungsnehmer"

FOOTER_ICON = "https://media.discordapp.net/attachments/1473692441726029874/1497915098310901861/IGv4.png?ex=69ef41a5&is=69edf025&hm=1840dd2e17a7eff7b28600d3ac2f4e3bc658ff0fb8f53f73e16292760088d87e&=&format=webp&quality=lossless&width=625&height=625"
AUTOMOD_ICON = "https://media.discordapp.net/attachments/1473692441726029874/1473692787156455474/1072-automod.png?ex=699722dc&is=6995d15c&hm=08ad340d3673e1f1076cbf73d235ea3b0e8ef10b07abb8d24ea66d85c6b59edb&=&format=webp&quality=lossless&width=250&height=250"
FOOTER_TEXT = "Copyright © InsuranceGuard v4"
AUTHOR_NAME = ""


# ═══════════════════════════════════════════════════════
#   HILFSFUNKTIONEN
# ═══════════════════════════════════════════════════════
async def send_to_log_channel(
    guild: discord.Guild, embed: discord.Embed, view: Optional[discord.ui.View] = None
):
    if config.get("log_channel_id"):
        try:
            ch = guild.get_channel(config["log_channel_id"])
            if ch:
                await ch.send(embed=embed, view=view)
        except Exception as e:
            logger.error(f"Log-Channel Fehler: {e}")


# ── DVG Embed-Builder ────────────────────────────────────────────────────────
def dvg_embed(title: str, description: str = "") -> discord.Embed:
    """
    Erstellt ein standardisiertes DVG-Embed.
    Unsichtbarer Rand (EMBED_COLOR = Discord-Embed-Hintergrund),
    einheitlicher Author + Footer gemäß DVG Corporate Design.
    """
    kwargs: dict = {"title": title, "color": EMBED_COLOR, "timestamp": get_now()}
    if description:
        kwargs["description"] = description
    e = discord.Embed(**kwargs)
    e.set_author(name=AUTHOR_NAME, icon_url=FOOTER_ICON)
    e.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
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
        e = discord.Embed(color=EMBED_COLOR, timestamp=get_now())
        e.add_field(name="Mitarbeiter", value=f"> {mitarbeiter.mention}", inline=False)
        e.add_field(name="Vorgang", value=f"> {vorgang}", inline=False)
        e.add_field(name="Anliegen", value=f"> {anliegen}", inline=False)
        e.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
        await ch.send(embed=e)
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
#   TRANSCRIPT — HTML GENERATOR (Discord-Style Dashboard)
# ═══════════════════════════════════════════════════════
def _esc(text: str) -> str:
    """HTML-escapet einen String und wandelt Zeilenumbrüche in <br> um."""
    return html_lib.escape(str(text)).replace("\n", "<br>")


def _render_embed_html(embed: discord.Embed) -> str:
    color = f"#{embed.color.value:06x}" if embed.color else "#5865f2"
    parts: List[str] = []
    if embed.title:
        if embed.url:
            parts.append(
                f'<a href="{html_lib.escape(embed.url)}" target="_blank" class="embed-title-link">{_esc(embed.title)}</a>'
            )
        else:
            parts.append(f'<div class="embed-title">{_esc(embed.title)}</div>')
    if embed.description:
        parts.append(f'<div class="embed-desc">{_esc(embed.description)}</div>')
    inline_group: List[str] = []
    for field in embed.fields:
        fh = f'<div class="field-block{"--inline" if field.inline else ""}"><div class="field-name">{_esc(field.name)}</div><div class="field-value">{_esc(field.value)}</div></div>'
        if field.inline:
            inline_group.append(fh)
        else:
            if inline_group:
                parts.append(f'<div class="field-row">{"".join(inline_group)}</div>')
                inline_group = []
            parts.append(fh)
    if inline_group:
        parts.append(f'<div class="field-row">{"".join(inline_group)}</div>')
    if embed.footer and embed.footer.text:
        parts.append(f'<div class="embed-footer">{_esc(embed.footer.text)}</div>')
    return f'<div class="embed" style="border-left:4px solid {color}">{"".join(parts)}</div>'


def generate_transcript_html(
    channel_name: str, customer_name: str, ticket_type: str, messages: list
) -> str:
    type_labels = {
        "schadensmeldung": "Schadensmeldung",
        "kundenkontakt": "Kundenkontakt",
    }
    type_label = type_labels.get(ticket_type, ticket_type.capitalize())
    msgs_html = ""
    prev_id = None

    for msg in messages:
        ts = msg.created_at.astimezone(GERMANY_TZ).strftime("%d.%m.%Y %H:%M")
        is_cont = (prev_id == msg.author.id) and not msg.embeds and not msg.attachments
        prev_id = msg.author.id

        av = (
            (str(msg.author.avatar.url).split("?")[0] + "?size=64")
            if msg.author.avatar
            else f"https://cdn.discordapp.com/embed/avatars/{msg.author.id % 6}.png"
        )
        uc = "#5865f2" if msg.author.bot else "#f2f3f5"

        body = ""
        if msg.content:
            body += f'<div class="msg-text">{_esc(msg.content)}</div>'
        for att in msg.attachments:
            body += f'<div class="attachment"><a href="{html_lib.escape(att.url)}" target="_blank">📎 {_esc(att.filename)}</a></div>'
        for emb in msg.embeds:
            body += _render_embed_html(emb)
        if not body:
            continue

        if not is_cont:
            msgs_html += f'''
<div class="msg-group">
  <img class="avatar" src="{av}" onerror="this.src='https://cdn.discordapp.com/embed/avatars/0.png'" loading="lazy">
  <div class="msg-body">
    <div class="msg-header">
      <span class="username" style="color:{uc}">{_esc(msg.author.display_name)}</span>
      {"<span class='bot-tag'>BOT</span>" if msg.author.bot else ""}
      <span class="ts">{ts}</span>
    </div>{body}
  </div>
</div>'''
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
.ts { color:#949ba4; font-size:11px }
.msg-text { white-space:pre-wrap; word-break:break-word }
.attachment { color:#00b0f4; font-size:13px; margin-top:3px }
.embed { background:#2b2d31; border-radius:0 4px 4px 0; padding:12px 16px; margin-top:4px; max-width:520px }
.embed-title { color:#fff; font-weight:600; margin-bottom:4px }
.embed-title-link { color:#00b0f4; font-weight:600; display:block; margin-bottom:4px }
.embed-desc { color:#dcddde; font-size:14px; margin-bottom:6px; white-space:pre-wrap; word-break:break-word }
.field-row { display:flex; flex-wrap:wrap; gap:12px; margin-top:6px }
.field-block, .field-block--inline { margin-top:6px }
.field-block--inline { flex:1; min-width:120px }
.field-name { color:#fff; font-weight:600; font-size:13px; margin-bottom:2px }
.field-value { color:#dcddde; font-size:14px; white-space:pre-wrap; word-break:break-word }
.embed-footer { color:#949ba4; font-size:12px; margin-top:8px; padding-top:8px; border-top:1px solid #3f4147 }
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
    <div class="ch-meta">Kunde: {_esc(customer_name)} &nbsp;·&nbsp; {len(messages)} Nachrichten &nbsp;·&nbsp; Export {get_now().strftime("%d.%m.%Y, %H:%M Uhr")}</div>
  </div>
</div>
<div class="messages">{msgs_html}</div>
<div class="footer">InsuranceGuard v4 &nbsp;·&nbsp; Ticket-Transcript</div>
</body>
</html>"""


async def generate_and_save_transcript(
    channel: discord.TextChannel, ticket_info: dict, messages: list
) -> Optional[str]:
    """Generiert das Transcript-HTML, speichert es, gibt die URL zurück (oder None)."""
    try:
        customer_id = ticket_info.get("customer_id", "")
        customer = data["customers"].get(customer_id, {})
        customer_name = customer.get("rp_name", customer_id or "Unbekannt")
        ticket_type = ticket_info.get("type", "")

        html_content = generate_transcript_html(
            channel.name, customer_name, ticket_type, messages
        )
        tid = str(uuid.uuid4())
        path = f"transcripts/{tid}.html"
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_content)

        if BOT_BASE_URL:
            return f"{BOT_BASE_URL}/transcript/{tid}"
        return None
    except Exception as e:
        logger.error(f"Transcript Generierungsfehler: {e}", exc_info=True)
        return None


# ═══════════════════════════════════════════════════════
#   TICKET CLOSE HELPER (DRY — inkl. Transcript)
# ═══════════════════════════════════════════════════════
async def close_ticket_channel(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    ticket_info: dict,
    auto_close: bool = False,
) -> None:
    closer_mention = interaction.user.mention if interaction else "System System"
    closer_id = getattr(interaction.user, "id", 0) if interaction else 0

    if interaction and not interaction.response.is_done():
        await interaction.response.defer()

    # ── Nachrichten + Transcript ─────────────────────────────────────────────
    messages = [msg async for msg in channel.history(limit=500, oldest_first=True)]
    transcript_url = await generate_and_save_transcript(channel, ticket_info, messages)

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

    # ── Close-Embed ──────────────────────────────────────────────────────────
    title_text = (
        "Ticket automatisch geschlossen" if auto_close else "Ticket geschlossen"
    )
    desc_parts = [
        "**Bearbeitung abgeschlossen.**"
        if not auto_close
        else "**Wegen Inaktivität automatisch geschlossen.**"
    ]
    desc_parts.append(
        f"> Kanal wird in **5 Sekunden** gelöscht." if not auto_close else ""
    )
    if duration_min:
        h, m = divmod(duration_min, 60)
        desc_parts.append(f"> Bearbeitungsdauer: `{h}h {m}min`")

    close_embed = dvg_embed(title_text, "\n".join(p for p in desc_parts if p))
    if not auto_close:
        close_embed.add_field(
            name="Geschlossen von", value=f"> {closer_mention}", inline=True
        )
    if transcript_url:
        close_embed.add_field(
            name="Transcript", value="> Über den Button unten abrufbar.", inline=False
        )

    view = discord.ui.View()
    if transcript_url:
        view.add_item(
            discord.ui.Button(label="Transcript anzeigen", url=transcript_url)
        )

    if interaction and interaction.response.is_done():
        if transcript_url:
            await interaction.followup.send(embed=close_embed, view=view)
        else:
            await interaction.followup.send(embed=close_embed)
    else:
        if transcript_url:
            await channel.send(embed=close_embed, view=view)
        else:
            await channel.send(embed=close_embed)

    # ── Log-Kanal ────────────────────────────────────────────────────────────
    log_e = dvg_embed(
        f"Ticket geschlossen{'  –  Inaktivität' if auto_close else ''}",
        f"> Kanal: `{channel.name}`",
    )
    log_e.add_field(name="Kunden-ID", value=f"> `{customer_id}`", inline=True)
    log_e.add_field(name="Geschlossen von", value=f"> {closer_mention}", inline=True)
    if duration_min:
        h, m = divmod(duration_min, 60)
        log_e.add_field(name="Bearbeitungsdauer", value=f"> `{h}h {m}min`", inline=True)

    if transcript_url:
        log_view = discord.ui.View()
        log_view.add_item(
            discord.ui.Button(label="Transcript anzeigen", url=transcript_url)
        )
        await send_to_log_channel(channel.guild, log_e, view=log_view)
    else:
        await send_to_log_channel(channel.guild, log_e)

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
            "transcript_url": transcript_url or "—",
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
    warn_embed = discord.Embed(
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
        value=f"> `{auto_close_time.strftime('%d.%m.%Y • %H:%M Uhr')}`",
        inline=False,
    )
    warn_embed.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)

    await channel.send(
        content=" ".join(pings) if pings else None,
        embed=warn_embed,
        view=InaktivitätsWarnView(),
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


# ── Autocomplete-Funktionen ─────────────────────────n��────────────────────────
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
        name="Zahlungsmethoden",
        value=f"> HBpay: `{customer.get('hbpay_nummer', '—')}`\n"
        f"> Economy-ID: `{customer.get('economy_id', '—')}`",
        inline=False,
    )
    try:
        await member.send(embed=dm)
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
    e = dvg_embed(title, f"> {description}")
    e.set_author(name=f"Berechtigungsprüfung · {AUTHOR_NAME}", icon_url=AUTOMOD_ICON)
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
    embed = dvg_embed("Versicherungsakte")
    embed.add_field(
        name="Versicherungsnehmer",
        value=f">  - {customer['rp_name']}\n>  - `{customer_id}`",
        inline=False,
    )
    embed.add_field(
        name="Zahlungsmethoden",
        value=f">  - `{customer['hbpay_nummer']}`\n>  - `{customer['economy_id']}`",
        inline=False,
    )
    ins_text = "\n".join(
        f"> {ins}\n> - `{ins_types.get(ins, {}).get('price', 0.0):,.2f} €/Monat`"
        for ins in customer.get("versicherungen", [])
    )
    embed.add_field(
        name="Abgeschlossene Versicherungen", value=ins_text or "> Keine", inline=False
    )
    embed.add_field(
        name="Gesamtbeitrag (monatlich)",
        value=f"> **`{total_price:,.2f} €`** zzgl. 3% Steuern",
        inline=False,
    )
    embed.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
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
            if (
                msg.author.id == (guild.me.id if guild.me else bot.user.id)
                and msg.embeds
            ):
                await msg.edit(embed=build_kundenakte_embed(customer_id, customer))
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

        embed = discord.Embed(
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
            value=f"> `{get_now().strftime('%d.%m.%Y, %H:%M Uhr')}`",
            inline=True,
        )
        embed.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)

        msg = await thread.send(embed=embed, file=file)
        data["customers"][customer_id]["backup_message_id"] = msg.id
        save_data(data)
    except Exception as e:
        logger.error(f"Kunden-Thread Backup Fehler ({customer_id}): {e}", exc_info=True)


# ═══════════════════════════════════════════════════════
#   MODUL-SYSTEM
# ═══════════════════════════════════════════════════════
IMMER_SICHTBAR = {"modul", "ping", "backup", "reload"}

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
        "portal-zugang",
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
    bot.add_view(KundenkontaktView())
    bot.add_view(SchadensmeldungView())
    bot.add_view(TicketCloseView(0, ""))  # Legacy-Compat für bestehende Tickets
    bot.add_view(SchadensmeldungTicketView())  # Neue Schadensmeldungs-Tickets
    bot.add_view(KundenkontaktTicketView())  # Neue Kundenkontakt-Tickets
    bot.add_view(InaktivitätsWarnView())  # Inaktivitätswarnung
    bot.add_view(AuszahlungActionView("dummy", "dummy", 0.0))

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
        else f"> **`{ms} ms`** — Stabile Verbindung!"
        if ms < 200
        else f"> **`{ms} ms`** — Schlechte Verbindung!"
    )
    embed = discord.Embed(
        title="Systemstatus InsuranceGuard v4", color=color, timestamp=get_now()
    )
    embed.add_field(name="Verbindung", value=status_val, inline=False)
    embed.add_field(
        name="Kunden",
        value=f"> - `{aktive}` Kunden\n> - `{archiviert}` ehem. Kunden",
        inline=True,
    )
    embed.add_field(
        name="Offene Vorgänge",
        value=f"> - **`{off_re}`** Rechnungen\n> - **`{aus_pend}`** Auszahlungen\n> - **`{offene_tk}`** Tickets",
        inline=True,
    )
    embed.add_field(
        name="Serverzeit",
        value=f"> `{get_now().strftime('%d.%m.%Y, %H:%M:%S Uhr')}`",
        inline=False,
    )
    embed.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ═══════════════════════════════════════════════════════
#   /modul
# ═══════════════════════════════════════════════════════
@bot.tree.command(
    name="modul", description="[ADMIN] Versicherungsmodul aktivieren oder deaktivieren"
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
            embed=build_error_embed(
                "Zugriff verweigert!",
                "Nur Administratoren können Module verwalten.",
                "Administrator",
            ),
            ephemeral=True,
        )
        return
    await interaction.response.defer(ephemeral=True)
    aktiv = aktion == "aktivieren"
    set_modul_config(interaction.guild_id, "versicherung", aktiv)
    aktive = get_aktive_module(interaction.guild_id)
    synced = await guild_sync(interaction.guild, aktive)
    icon = "" if aktiv else ""
    e = discord.Embed(
        title="Modul aktiviert!" if aktiv else "Modul deaktiviert!",
        description=(
            f"> **Versicherungsfirma** wurde {'aktiviert' if aktiv else 'deaktiviert'}!\n"
            f"> - **`{len(synced)}`** Befehle synchronisiert"
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
    e.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
    await interaction.followup.send(embed=e, ephemeral=True)
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
            embed=build_error_embed(
                "Zugriff verweigert!",
                "Nur die Leitungsebene kann Backups herunterladen.",
                "Leitungsebene",
            ),
            ephemeral=True,
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
            "## Vollständiger Datenbank-Export", file=file, ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(f" Fehler: {e}", ephemeral=True)


@bot.tree.command(
    name="reload", description="Stellt eine Datenbank-Datei (JSON) wieder her"
)
@app_commands.describe(datei="insurance_data.json oder bot_config.json")
async def reload_backup(interaction: discord.Interaction, datei: discord.Attachment):
    if not is_leitungsebene(interaction):
        await interaction.response.send_message(
            embed=build_error_embed(
                "Zugriff verweigert!",
                "Nur die Leitungsebene kann Backups wiederherstellen.",
                "Leitungsebene",
            ),
            ephemeral=True,
        )
        return
    if not datei.filename.endswith(".json"):
        await interaction.response.send_message(
            embed=build_error_embed(
                "Falscher Dateityp!", "Nur `.json` Dateien sind erlaubt."
            ),
            ephemeral=True,
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
                " `insurance_data.json` wiederhergestellt.", ephemeral=True
            )
        elif "log_channel_id" in json_obj or "insurance_types" in json_obj:
            global config
            config = json_obj
            save_config(config)
            await interaction.followup.send(
                " `bot_config.json` wiederhergestellt.", ephemeral=True
            )
        else:
            await interaction.followup.send(" Unbekanntes Dateiformat.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f" Fehler: {e}", ephemeral=True)


# ═══════════════════════════════════════════════════════
#   KUNDEN-SUCHE
# ═══════════════════════════════════════════════════════
@bot.tree.command(
    name="kunden-suchen",
    description="Sucht nach Kunden anhand des RP-Namens oder der Kunden-ID",
)
@app_commands.describe(suchbegriff="RP-Name, Kunden-ID, Kartennummer oder Economy-ID")
async def kunden_suchen(interaction: discord.Interaction, suchbegriff: str):
    if not is_mitarbeiter(interaction):
        await interaction.response.send_message(
            embed=build_error_embed(
                "Zugriff verweigert!",
                "Nur Mitarbeiter können die Kundensuche verwenden.",
                "Mitarbeiter",
            ),
            ephemeral=True,
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
            or q in c.get("economy_id", "").lower()
        ]
        if not treffer:
            embed = discord.Embed(
                title="Keine Suchergebnisse!",
                description=f"> Für `{suchbegriff}` wurden keine Kunden gefunden.",
                color=EMBED_COLOR,
                timestamp=get_now(),
            )
            embed.add_field(
                name="Suchtipps",
                value="> - Kunden-ID: `VN-26123456`\n> - RP-Name: `Max Mustermann`\n> - Kartennummer oder Economy-ID",
                inline=False,
            )
            embed.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="Suchergebnisse",
            description=f"> `-` Suchbegriff: `{suchbegriff}`\n> `-` Ergebnisse: `{len(treffer)}`",
            color=EMBED_COLOR,
            timestamp=get_now(),
        )
        for cid, c in treffer[:10]:
            status_text = " Aktiv" if c.get("status") == "aktiv" else " Archiviert"
            thread_id = c.get("thread_id")
            versicherungen = (
                "\n".join(f"> - {ins}" for ins in c.get("versicherungen", []))
                or "> - Keine"
            )
            embed.add_field(
                name=f"{c['rp_name']}",
                value=(
                    f">  - `{cid}`\n"
                    f">  - `{c['hbpay_nummer']}`\n"
                    f">  - `{c['economy_id']}`\n"
                    f">  - {status_text}\n"
                    f">  - `{c.get('total_monthly_price', 0):,.2f} €/Monat`\n"
                    + versicherungen[:200]
                    + "\n"
                    + (f">  - <#{thread_id}>" if thread_id else ">  - *Keine Akte!*")
                ),
                inline=False,
            )
        embed.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        logger.error(f"Kundensuche Fehler: {e}", exc_info=True)
        await interaction.followup.send(
            embed=build_error_embed("Fehler!", str(e)), ephemeral=True
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
                description=f"Beitrag: {ins_types.get(ins, {}).get('price', 0):,.2f} €/Mo",
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
        for item in view.children:
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
            value=f"> Wegfall: `-{wegfall:,.2f} €`\n> Neuer Beitrag: **`{neu_total:,.2f} €`**",
            inline=False,
        )
        e.set_footer(
            text="Diese Aktion kann nicht rückgängig gemacht werden • Copyright © InsuranceGuard v4",
            icon_url=FOOTER_ICON,
        )
        await interaction.response.edit_message(embed=e, view=view)


class KündigungView(discord.ui.View):
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
            embed=build_error_embed(
                "Zugriff verweigert!",
                "Nur Mitarbeiter können Versicherungen kündigen.",
                "Mitarbeiter",
            ),
            ephemeral=True,
        )
        return
    if customer_id not in data["customers"]:
        await interaction.response.send_message(
            embed=build_error_embed(
                "Nicht gefunden!", f"Keine Kundenakte mit ID `{customer_id}`."
            ),
            ephemeral=True,
        )
        return
    customer = data["customers"][customer_id]
    if not customer.get("versicherungen"):
        await interaction.response.send_message(
            embed=dvg_embed("Keine Versicherungen!", "> Keine aktiven Versicherungen."),
            ephemeral=True,
        )
        return

    # ── Kündigungsfrist prüfen: mind. 4 bezahlte Rechnungen (4 Monatsbeiträge) ──
    kündigung_erlaubt, paid_count = can_cancel_insurance(customer_id)
    if not kündigung_erlaubt:
        fehlende = 4 - paid_count
        singular = fehlende == 1
        e = dvg_embed(
            "Kündigung nicht möglich — Mindestlaufzeit",
            f"> Versicherungen können erst nach **4 geleisteten Monatsbeiträgen** gekündigt werden.\n"
            f"> Diese Regelung schützt vor missbräuchlicher Nutzung des Versicherungsschutzes.",
        )
        e.add_field(
            name="Bezahlte Rechnungen",
            value=f"> `{paid_count}` von `4` erforderlichen",
            inline=True,
        )
        e.add_field(
            name="Verbleibend",
            value=f"> `{fehlende}` weiterer Monatsbeitrag"
            if singular
            else f"> `{fehlende}` weitere Monatsbeiträge",
            inline=True,
        )
        e.add_field(
            name="Versicherungsnehmer",
            value=f"> {customer['rp_name']} (`{customer_id}`)",
            inline=False,
        )
        await interaction.response.send_message(embed=e, ephemeral=True)
        return

    ins_types = get_insurance_types()
    ins_text = "\n".join(
        f">  {ins} — `{ins_types.get(ins, {}).get('price', 0):,.2f} €/Mo`"
        for ins in customer.get("versicherungen", [])
    )
    view = KündigungView(customer_id, customer)
    e = dvg_embed(
        "Versicherung kündigen", "> Wählen Sie die zu kündigenden Versicherungen."
    )
    e.add_field(
        name="Versicherungsnehmer",
        value=f">  - {customer['rp_name']}\n>  - `{customer_id}`",
        inline=False,
    )
    e.add_field(name="Aktive Versicherungen", value=ins_text or "> Keine", inline=False)
    e.add_field(
        name="Aktueller Monatsbeitrag",
        value=f">  **`{customer.get('total_monthly_price', 0):,.2f} €`**",
        inline=False,
    )
    e.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
    await interaction.response.send_message(embed=e, view=view, ephemeral=True)
    await view.wait()

    if not view.confirmed:
        await interaction.edit_original_response(
            embed=dvg_embed("Kündigung abgebrochen."), view=None
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
                    value=f"> `{new_total:,.2f} €`",
                    inline=True,
                )
                v.add_field(
                    name="Durchgeführt von",
                    value=f"> {interaction.user.mention}",
                    inline=True,
                )
                v.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
                await thread.send(embed=v)
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
            name="Neuer Monatsbeitrag", value=f"> `{new_total:,.2f} €`", inline=False
        )
        dm.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
        try:
            await member.send(embed=dm)
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
    log_e.add_field(name="Neuer Beitrag", value=f"> `{new_total:,.2f} €`", inline=True)
    log_e.add_field(
        name="Durchgeführt von", value=f"> {interaction.user.mention}", inline=True
    )
    log_e.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
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
        name="Neuer Monatsbeitrag", value=f">  **`{new_total:,.2f} €`**", inline=False
    )
    s.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
    await interaction.edit_original_response(embed=s, view=None)


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
            embed=build_error_embed(
                "Zugriff verweigert!",
                "Nur die Leitungsebene kann Rechnungsübersichten einsehen.",
                "Leitungsebene",
            ),
            ephemeral=True,
        )
        return
    await interaction.response.defer(ephemeral=True)
    try:
        if customer_id and customer_id not in data["customers"]:
            await interaction.followup.send(
                embed=build_error_embed(
                    "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
                ),
                ephemeral=True,
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
                embed=dvg_embed("Keine Rechnungen", "> Keine Rechnungen gefunden."),
                ephemeral=True,
            )
            return

        sorted_inv = sorted(
            gefiltert.items(), key=lambda x: x[1].get("created_at", ""), reverse=True
        )
        embed = discord.Embed(
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
                    f">  - {cust.get('rp_name', '—')}\n"
                    f">  - `{inv['betrag']:,.2f} €`\n"
                    f"> Fällig: `{due.strftime('%d.%m.%Y')}`\n"
                    f">  {status_text}"
                    + (f"\n> Mahnstufe: `{mahn}`" if mahn > 0 else "")
                ),
                inline=True,
            )
        embed.add_field(
            name="Offene Summe", value=f"> **`{total_offen:,.2f} €`**", inline=False
        )
        embed.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        logger.error(f"Rechnungsübersicht Fehler: {e}", exc_info=True)
        await interaction.followup.send(
            embed=build_error_embed("Fehler!", str(e)), ephemeral=True
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
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur Administratoren.", "Administrator"
            ),
            ephemeral=True,
        )
        return
    if not (0 <= prozent <= 100):
        await interaction.response.send_message(
            embed=build_error_embed("Ungültiger Wert!", "0–100."), ephemeral=True
        )
        return
    config["steuer_prozent"] = prozent
    save_config(config)
    e = discord.Embed(
        title="Steuersatz aktualisiert!",
        description=f"> Neuer Steuersatz: **`{prozent}%`**",
        color=EMBED_COLOR,
    )
    e.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
    await interaction.response.send_message(embed=e, ephemeral=True)
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
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur Administratoren.", "Administrator"
            ),
            ephemeral=True,
        )
        return
    if name in config["insurance_types"]:
        await interaction.response.send_message(
            embed=build_error_embed(
                "Bereits vorhanden!", f"`{name}` existiert bereits."
            ),
            ephemeral=True,
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
    e.add_field(name="Preis", value=f"> `{preis:,.2f} €/Monat`", inline=True)
    e.add_field(name="Limit", value=f"> `{auszahlungslimit:,.2f} €`", inline=True)
    e.add_field(name="Rolle", value=f"> `{role}`", inline=True)
    e.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
    await interaction.response.send_message(embed=e, ephemeral=True)
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
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur Administratoren.", "Administrator"
            ),
            ephemeral=True,
        )
        return
    if name not in config["insurance_types"]:
        await interaction.response.send_message(
            embed=build_error_embed("Nicht gefunden!", f"Keine Versicherung `{name}`."),
            ephemeral=True,
        )
        return
    changes = []
    if neuer_preis >= 0.0:
        config["insurance_types"][name]["price"] = neuer_preis
        changes.append(f"Preis: `{neuer_preis:,.2f} €`")
    if neues_limit >= 0.0:
        config["insurance_types"][name]["auszahlung_limit"] = neues_limit
        changes.append(f"Limit: `{neues_limit:,.2f} €`")
    if aktiviert is not None:
        config["insurance_types"][name]["enabled"] = aktiviert
        changes.append(f"Status: `{'Aktiv' if aktiviert else 'Deaktiviert'}`")
    if not changes:
        await interaction.response.send_message(
            "Keine Änderungen angegeben.", ephemeral=True
        )
        return
    save_config(config)
    e = discord.Embed(
        title=f"Versicherung `{name}` aktualisiert!",
        description="\n".join(f"> {c}" for c in changes),
        color=EMBED_COLOR,
    )
    e.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.command(
    name="einstellung-versicherungen-liste",
    description="[ADMIN] Zeigt alle konfigurierten Versicherungen",
)
async def list_versicherungen(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message(
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur Administratoren.", "Administrator"
            ),
            ephemeral=True,
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
            value=f"> Preis: `{v['price']:,.2f} €/Mo`\n> Limit: `{v['auszahlung_limit']:,.2f} €`\n> Rolle: `{v['role']}`",
            inline=True,
        )
    e.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
    await interaction.response.send_message(embed=e, ephemeral=True)


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
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur Administratoren.", "Administrator"
            ),
            ephemeral=True,
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
            name="KK-Panel",
            value=ch(config.get("kundenkontakt_channel_id")),
            inline=True,
        )
        e.add_field(
            name="SM-Panel",
            value=ch(config.get("schadensmeldung_channel_id")),
            inline=True,
        )
        e.add_field(
            name="KK-Kategorie",
            value=cat(config.get("kundenkontakt_category_id")),
            inline=True,
        )
        e.add_field(
            name="SM-Kategorie",
            value=cat(config.get("schadensmeldung_category_id")),
            inline=True,
        )
        e.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
        await interaction.response.send_message(embed=e, ephemeral=True)
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
                value="> - Gültige **Kunden-ID** erforderlich!\n> - Kontaktgrund **detailliert** beschreiben!\n> - Nur für **Mitarbeiter** und **Leitungsebene**!\n> - Pro Mitarbeiter nur **ein aktives Ticket** gleichzeitig!",
                inline=False,
            )
            embed_kk.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
            await kundenkontakt_panel.send(embed=embed_kk, view=KundenkontaktView())
            changes.append(f"KK-Panel: {kundenkontakt_panel.mention}")
            panel_results.append(f" Kundenkontakt-Panel gesendet")
        except Exception as ex:
            panel_results.append(f" Fehler KK-Panel: {ex}")

    if schadensmeldung_panel:
        try:
            config["schadensmeldung_channel_id"] = schadensmeldung_panel.id
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
                value="> - **Kunden-ID**\n> - **Geschädigter** (RP-Name)\n> - **Täter** (RP-Name)\n> - **Vorfallbeschreibung**\n> - **Rechnung/Nachweis**",
                inline=False,
            )
            # Voraussichtliche Bearbeitungszeit aus ticket_stats berechnen
            sm_stats = [
                s
                for s in data.get("ticket_stats", [])
                if s.get("type") == "schadensmeldung" and s.get("duration_minutes")
            ]
            if sm_stats:
                avg_m = int(
                    sum(s["duration_minutes"] for s in sm_stats) / len(sm_stats)
                )
                h, m = divmod(avg_m, 60)
                avg_tx = f"`{h}h {m}min`" if h else f"`{m} Minuten`"
                bearbzeit = f"> Voraussichtliche Bearbeitungszeit: {avg_tx}\n> Basierend auf {len(sm_stats)} abgeschlossenen Vorgängen."
            else:
                bearbzeit = "> Voraussichtliche Bearbeitungszeit: **wird nach ersten Vorgängen ermittelt**"
            embed_sm.add_field(name="Bearbeitungszeit", value=bearbzeit, inline=False)
            embed_sm.add_field(
                name="Hinweis",
                value="> Pro Kunden nur **eine aktive Schadensmeldung** gleichzeitig!",
                inline=False,
            )
            embed_sm.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
            await schadensmeldung_panel.send(embed=embed_sm, view=SchadensmeldungView())
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
    e.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
    await interaction.followup.send(embed=e, ephemeral=True)


# ═══════════════════════════════════════════════════════
#   KUNDENAKTE ERSTELLEN
# ═══════════════════════════════════════════════════════
class InsuranceSelect(discord.ui.Select):
    def __init__(self):
        ins_types = get_insurance_types()
        options = [
            discord.SelectOption(
                label=ins,
                description=f"Monatsbeitrag: {info['price']:,.2f} €",
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
        for item in view.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = False
        ins_types = get_insurance_types()
        total = sum(ins_types[ins]["price"] for ins in self.values)
        preview = "\n".join(
            f"> - {ins} — {ins_types[ins]['price']:,.2f} €" for ins in self.values
        )
        e = discord.Embed(
            title="Versicherungen ausgewählt!",
            description=f"{preview}\n\n**Gesamtbeitrag:** `{total:,.2f} €`",
            color=EMBED_COLOR,
        )
        e.set_footer(text="Klicken Sie auf 'Kundenakte erstellen', um fortzufahren.")
        await interaction.response.edit_message(embed=e, view=view)


class InsuranceView(discord.ui.View):
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
                description=f"Monatsbeitrag: {info['price']:,.2f} €",
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
        for item in view.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = False
        ins_types = get_insurance_types()
        total = sum(ins_types[ins]["price"] for ins in self.values)
        e = discord.Embed(
            title="Neue Versicherungen ausgewählt!",
            description="\n".join(
                f"> - {ins} — {ins_types[ins]['price']:,.2f} €" for ins in self.values
            )
            + f"\n\n**Zusätzlicher Beitrag:** `{total:,.2f} €`",
            color=EMBED_COLOR,
        )
        await interaction.response.edit_message(embed=e, view=view)


class AddInsuranceView(discord.ui.View):
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
    economy_id="Economy-ID",
)
async def create_customer(
    interaction: discord.Interaction,
    forum_channel: discord.ForumChannel,
    user: discord.Member,
    rp_name: str,
    hbpay_nummer: str,
    economy_id: str,
):
    if not is_mitarbeiter(interaction):
        await interaction.response.send_message(
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter / Leitungsebene"
            ),
            ephemeral=True,
        )
        return
    view = InsuranceView()
    select_embed = dvg_embed(
        "Versicherungen auswählen!",
        "> Bitte wählen Sie die gewünschten Versicherungen aus dem Dropdown-Menü.",
    )
    await interaction.response.send_message(
        embed=select_embed, view=view, ephemeral=True
    )
    await view.wait()
    if not view.confirmed:
        await interaction.edit_original_response(
            embed=dvg_embed("Zeitüberschreitung!"), view=None
        )
        return
    ins_list = view.children[0].values
    if not ins_list:
        await interaction.edit_original_response(
            embed=dvg_embed("Keine Auswahl!"), view=None
        )
        return

    ins_types = get_insurance_types()
    try:
        customer_id = generate_customer_id()
        total_price = sum(ins_types[ins]["price"] for ins in ins_list)
        customer_data = {
            "rp_name": rp_name,
            "hbpay_nummer": hbpay_nummer,
            "economy_id": economy_id,
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
            name=f" {customer_id} | {rp_name}", content="", embed=embed
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

        # ── Portal-Token automatisch erstellen und per DM senden ────────────────
        token = generate_portal_token(customer_id)
        portal_url = f"{BOT_BASE_URL}/portal/{token}" if BOT_BASE_URL else None

        dm_embed = build_kundenakte_embed(customer_id, customer_data)
        dm_embed.title = "Willkommen bei DVG InsuranceGuard!"
        dm_embed.description = "Ihre Versicherungsakte wurde erfolgreich angelegt."
        if portal_url:
            dm_embed.add_field(
                name="Ihr Kundenportal",
                value="> Ueber den Button unten gelangen Sie jederzeit zu Ihrer persoenlichen Versicherungsübersicht.",
                inline=False,
            )
        dm_view = discord.ui.View()
        if portal_url:
            dm_view.add_item(
                discord.ui.Button(label="Zum Kundenportal", url=portal_url)
            )
        try:
            dm_msg = await user.send(
                embed=dm_embed, view=dm_view if portal_url else None
            )
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

        log_e = dvg_embed("Neue Kundenakte erstellt!")
        log_e.add_field(
            name="Versicherungsnehmer",
            value=f"> {rp_name}\n> `{customer_id}`",
            inline=False,
        )
        log_e.add_field(name="Discord", value=f"> {user.mention}", inline=True)
        log_e.add_field(
            name="Monatsbeitrag", value=f"> `{total_price:,.2f} €`", inline=True
        )
        log_e.add_field(
            name="Aussteller", value=f"> {interaction.user.mention}", inline=False
        )
        log_e.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
        await send_to_log_channel(interaction.guild, log_e)

        s = dvg_embed("Kundenakte erfolgreich angelegt!")
        s.add_field(
            name="Informationen",
            value=f">  `{customer_id}`\n>  {thread.thread.mention}\n>  `{total_price:,.2f} €`\n>   DM gesendet!",
            inline=False,
        )
        s.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
        await interaction.edit_original_response(embed=s, view=None)
    except Exception as e:
        logger.error(f"Kundenakte Fehler: {e}", exc_info=True)
        await interaction.edit_original_response(
            embed=discord.Embed(title="Fehler!", description=str(e), color=EMBED_COLOR),
            view=None,
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
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
            ),
            ephemeral=True,
        )
        return
    if customer_id not in data["customers"]:
        await interaction.response.send_message(
            embed=build_error_embed(
                "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
            ),
            ephemeral=True,
        )
        return
    customer = data["customers"][customer_id]
    existing = customer.get("versicherungen", [])
    ins_types = get_insurance_types()
    if not [ins for ins in ins_types if ins not in existing]:
        await interaction.response.send_message(
            embed=dvg_embed("Alle Versicherungen abgeschlossen!"), ephemeral=True
        )
        return
    view = AddInsuranceView(existing)
    e = discord.Embed(
        title="Versicherung nachbuchen",
        description=f"Kunde: **{customer['rp_name']}** (`{customer_id}`)\n\nBitte wähle die hinzuzufügenden Versicherungen.",
        color=EMBED_COLOR,
    )
    await interaction.response.send_message(embed=e, view=view, ephemeral=True)
    await view.wait()
    if not view.confirmed:
        await interaction.edit_original_response(
            embed=dvg_embed("Abgebrochen."), view=None
        )
        return
    new_insurances = view.children[0].values
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
            value="\n".join(f"> - {ins}" for ins in new_insurances),
            inline=False,
        )
        dm.add_field(
            name="Neuer Monatsbeitrag", value=f"> `{new_total:,.2f} €`", inline=False
        )
        dm.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
        try:
            await member.send(embed=dm)
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
        value="\n".join(f"> - {ins}" for ins in new_insurances),
        inline=False,
    )
    s.add_field(
        name="Neuer Monatsbeitrag", value=f"> `{new_total:,.2f} €`", inline=False
    )
    s.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
    await interaction.edit_original_response(embed=s, view=None)


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
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
            ),
            ephemeral=True,
        )
        return
    await interaction.response.defer(ephemeral=True)
    try:
        if customer_id not in data["customers"]:
            await interaction.followup.send(
                embed=build_error_embed(
                    "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
                ),
                ephemeral=True,
            )
            return
        customer = data["customers"][customer_id]

        # Prüfen ob bereits eine offene Rechnung existiert
        existing_inv = customer_has_unpaid_invoice(customer_id)
        if existing_inv:
            await interaction.followup.send(
                embed=build_error_embed(
                    "Offene Rechnung vorhanden!",
                    f"Für **{customer['rp_name']}** existiert bereits eine offene Rechnung (`{existing_inv}`).\nBitte archivieren Sie diese zuerst, bevor eine neue ausgestellt werden kann.",
                ),
                ephemeral=True,
            )
            return

        invoice_id = generate_invoice_id()
        betrag_netto = customer["total_monthly_price"]
        steuer_prozent = config.get("steuer_prozent", 3.0)
        steuer = betrag_netto * (steuer_prozent / 100)
        betrag_brutto = betrag_netto + steuer
        due_date = get_now() + timedelta(days=3)
        ins_types = get_insurance_types()

        embed = discord.Embed(
            title=f"Versicherungsrechnung - {get_now().strftime('%d.%m.%Y')}",
            description="Dies ist eine Zahlungsaufforderung für Ihre Versicherungsbeiträge!",
            color=EMBED_COLOR,
            timestamp=get_now(),
        )
        embed.add_field(name="Rechnungsinformationen", value=f">  - `{invoice_id}`")
        embed.add_field(
            name="Versicherungsnehmer",
            value=f">  - {customer['rp_name']}\n>  - `{customer_id}`",
            inline=False,
        )
        embed.add_field(
            name="Zahlungsmethoden",
            value=f">  - `{customer['hbpay_nummer']}`\n>  - `{customer['economy_id']}`",
            inline=False,
        )
        ins_details = "\n".join(
            f"> {ins}\n> - `{ins_types.get(ins, {}).get('price', 0.0):,.2f} €`"
            for ins in customer["versicherungen"]
        )
        embed.add_field(
            name="Abgeschlossene Versicherungen", value=ins_details, inline=False
        )
        embed.add_field(
            name="Zwischensumme (Netto)",
            value=f"> `{betrag_netto:,.2f} €`",
            inline=False,
        )
        embed.add_field(
            name=f"Steuer ({steuer_prozent}%)",
            value=f"> `+ {steuer:,.2f} €`",
            inline=False,
        )
        embed.add_field(
            name="Rechnungsbetrag (Brutto)",
            value=f" **`{betrag_brutto:,.2f} €`**",
            inline=False,
        )
        embed.add_field(
            name="Status: Zahlung ausstehend!",
            value=f"> Bis zum **{due_date.strftime('%d.%m.%Y')}** bezahlen.",
            inline=False,
        )
        embed.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)

        message = await channel.send(embed=embed)
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
            anliegen=f"`{betrag_brutto:,.2f} €` — {customer['rp_name']} (`{customer_id}`)",
        )

        s = dvg_embed("Rechnung erfolgreich ausgestellt!")
        s.add_field(name="Rechnungsnummer", value=f"> `{invoice_id}`", inline=True)
        s.add_field(name="Betrag", value=f"> `{betrag_brutto:,.2f} €`", inline=True)
        s.add_field(
            name="Fällig", value=f"> {due_date.strftime('%d.%m.%Y')}", inline=True
        )
        s.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
        await interaction.followup.send(embed=s, ephemeral=True)
    except Exception as e:
        logger.error(f"Rechnung Fehler: {e}", exc_info=True)
        await interaction.followup.send(
            embed=build_error_embed("Fehler!", str(e)), ephemeral=True
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
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
            ),
            ephemeral=True,
        )
        return
    await interaction.response.defer(ephemeral=True)
    try:
        if invoice_id not in data["invoices"]:
            await interaction.followup.send(
                embed=build_error_embed(
                    "Nicht gefunden!", f"Keine Rechnung `{invoice_id}`."
                ),
                ephemeral=True,
            )
            return
        invoice = data["invoices"][invoice_id]
        if invoice.get("paid", False):
            await interaction.followup.send(
                embed=dvg_embed("Bereits archiviert!"), ephemeral=True
            )
            return
        customer_id = invoice["customer_id"]
        customer = data["customers"].get(customer_id)
        if not customer:
            await interaction.followup.send(
                embed=build_error_embed(
                    "Nicht gefunden!", f"Kunde `{customer_id}` nicht gefunden."
                ),
                ephemeral=True,
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
                if msg.embeds:
                    upd = msg.embeds[0]
                    upd.color = COLOR_SUCCESS
                    for i, field in enumerate(upd.fields):
                        if "Status" in field.name:
                            upd.set_field_at(
                                i,
                                name="Status: Bezahlt!",
                                value=f"> Bezahlt am **{get_now().strftime('%d.%m.%Y • %H:%M Uhr')}**\n> Archiviert von: {interaction.user.mention}",
                                inline=False,
                            )
                            break
                    await msg.edit(embed=upd)
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
                        "Bezahlt. Auszahlungslimit zurückgesetzt.",
                    )
                    ae.add_field(
                        name="Rechnungs-Nr.", value=f"> `{invoice_id}`", inline=True
                    )
                    ae.add_field(
                        name="Betrag",
                        value=f"> `{invoice['betrag']:,.2f} €`",
                        inline=True,
                    )
                    ae.add_field(
                        name="Archiviert von",
                        value=f"> {interaction.user.mention}",
                        inline=False,
                    )
                    ae.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
                    await thread.send(embed=ae)
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

        s = discord.Embed(
            title="Rechnung archiviert!",
            description=f"`{invoice_id}` als bezahlt markiert.",
            color=EMBED_COLOR,
        )
        s.add_field(name="Kunde", value=f"> {customer['rp_name']}", inline=True)
        s.add_field(name="Betrag", value=f"> `{invoice['betrag']:,.2f} €`", inline=True)
        s.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
        await interaction.followup.send(embed=s, ephemeral=True)
    except Exception as e:
        logger.error(f"Archivieren Fehler: {e}", exc_info=True)
        await interaction.followup.send(
            embed=build_error_embed("Fehler!", str(e)), ephemeral=True
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
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
            ),
            ephemeral=True,
        )
        return
    await interaction.response.defer(ephemeral=True)
    try:
        if invoice_id not in data["invoices"]:
            await interaction.followup.send(
                embed=build_error_embed(
                    "Nicht gefunden!", f"Keine Rechnung `{invoice_id}`."
                ),
                ephemeral=True,
            )
            return
        invoice = data["invoices"][invoice_id]
        if invoice.get("paid", False):
            await interaction.followup.send(
                embed=dvg_embed("Bereits bezahlt!"), ephemeral=True
            )
            return
        customer = data["customers"].get(invoice["customer_id"])
        if not customer:
            await interaction.followup.send(
                embed=build_error_embed("Nicht gefunden!", "Kunde nicht gefunden."),
                ephemeral=True,
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

        s = discord.Embed(
            title=f"{reminder_count}. Mahnung ausgestellt!",
            description=f"Rechnung `{invoice_id}`",
            color=EMBED_COLOR,
        )
        s.add_field(
            name="Neuer Betrag",
            value=f"> `{data['invoices'][invoice_id]['betrag']:,.2f} €`",
            inline=True,
        )
        if surcharge_pct > 0:
            s.add_field(name="Mahngebühr", value=f"> +{surcharge_pct}%", inline=True)
        s.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
        await interaction.followup.send(embed=s, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(
            embed=build_error_embed("Fehler!", str(e)), ephemeral=True
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
            embed = discord.Embed(
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
                value=f"> Ursprünglich: `{invoice_data['original_betrag']:,.2f} €`\n> **Aktuell: `{invoice_data['betrag']:,.2f} €`**{surcharge_tx}",
                inline=False,
            )
            embed.set_footer(
                text="Bitte begleichen Sie den Betrag umgehend • Copyright © InsuranceGuard v4",
                icon_url=FOOTER_ICON,
            )
            await channel.send(member.mention if member else "", embed=embed)
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
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
            ),
            ephemeral=True,
        )
        return
    await interaction.response.defer(ephemeral=True)
    try:
        if customer_id not in data["customers"]:
            await interaction.followup.send(
                embed=build_error_embed(
                    "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
                ),
                ephemeral=True,
            )
            return
        customer = data["customers"][customer_id]
        if customer.get("status") == "archiviert":
            await interaction.followup.send(
                embed=dvg_embed("Bereits archiviert!"), ephemeral=True
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
                        value=f"> {get_now().strftime('%d.%m.%Y • %H:%M Uhr')}",
                        inline=True,
                    )
                    ae.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
                    await thread.send(embed=ae)
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

        s = discord.Embed(
            title="Akte archiviert!",
            description=f"Kundenakte `{customer_id}` archiviert und alle Rollen entfernt.",
            color=EMBED_COLOR,
        )
        s.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
        await interaction.followup.send(embed=s, ephemeral=True)
    except Exception as e:
        logger.error(f"Archivieren Fehler: {e}", exc_info=True)
        await interaction.followup.send(
            embed=build_error_embed("Fehler!", str(e)), ephemeral=True
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
                await interaction.followup.send(" Ungültiger Betrag.", ephemeral=True)
                return

            verfügbar = get_verfügbares_guthaben(self.customer_id, self.versicherung)
            ins_types = get_insurance_types()
            limit = ins_types.get(self.versicherung, {}).get("auszahlung_limit", 0.0)

            if betrag_float <= 0:
                await interaction.followup.send(
                    " Betrag muss > 0 sein.", ephemeral=True
                )
                return
            if betrag_float > verfügbar:
                await interaction.followup.send(
                    f" Betrag überschreitet verfügbares Guthaben `{verfügbar:,.2f} €`.",
                    ephemeral=True,
                )
                return

            az_channel_id = config.get("auszahlung_channel_id")
            if not az_channel_id:
                await interaction.followup.send(
                    " Auszahlungs-Kanal nicht konfiguriert.", ephemeral=True
                )
                return
            az_channel = interaction.guild.get_channel(az_channel_id)
            if not az_channel:
                await interaction.followup.send(
                    " Auszahlungs-Kanal nicht gefunden.", ephemeral=True
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
                value=f">  `{auszahlung_id}`\n>  `{betrag_float:,.2f} €`",
                inline=False,
            )
            embed.add_field(
                name="Versicherungsnehmer",
                value=f">  {self.customer['rp_name']}\n>  `{self.customer_id}`",
                inline=False,
            )
            embed.add_field(
                name="Versicherung",
                value=f"> {self.versicherung}\n> - `{verfügbar:,.2f} €` von `{limit:,.2f} €` verfügbar!",
                inline=False,
            )
            embed.add_field(
                name="Beschreibung", value=f"```{beschreibung_tx}```", inline=False
            )
            embed.add_field(
                name="Eingereicht von", value=f"{interaction.user.mention}", inline=True
            )
            embed.add_field(name="Status", value=">  Ausstehend", inline=True)
            embed.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)

            action_view = AuszahlungActionView(
                auszahlung_id, self.customer_id, betrag_float
            )
            msg = await az_channel.send(
                content=f"{ping_text} — Neuer Auszahlungsantrag!",
                embed=embed,
                view=action_view,
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

            s = discord.Embed(
                title="Auszahlungsantrag eingereicht!",
                description=f"Antrag `{auszahlung_id}` wurde weitergeleitet.",
                color=EMBED_COLOR,
            )
            s.add_field(name="Betrag", value=f"> `{betrag_float:,.2f} €`", inline=True)
            s.add_field(
                name="Versicherung", value=f"> `{self.versicherung}`", inline=True
            )
            s.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
            await interaction.followup.send(embed=s, ephemeral=True)
        except Exception as e:
            logger.error(f"Auszahlung Einreichen Fehler: {e}", exc_info=True)
            await interaction.followup.send(f" Fehler: {e}", ephemeral=True)


class AuszahlungSelectView(discord.ui.View):
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
                    description=f"Verfügbar: {verfügbar:,.0f} € | Ausgezahlt: {bereits:,.0f} € / {limit:,.0f} €"[
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
                f" Limit für `{selected}` ausgeschöpft.", ephemeral=True
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
                await interaction.followup.send(" Bereits bearbeitet.", ephemeral=True)
                return
            customer_id = pending["customer_id"]
            versicherung = pending["versicherung"]
            betrag = pending["betrag"]
            customer = data["customers"].get(customer_id)
            if not customer:
                await interaction.followup.send(
                    " Kunde nicht gefunden.", ephemeral=True
                )
                return
            verfügbar = get_verfügbares_guthaben(customer_id, versicherung)
            if betrag > verfügbar:
                await interaction.followup.send(
                    f" Guthaben reicht nicht aus (`{verfügbar:,.2f} €` verfügbar).",
                    ephemeral=True,
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
                            name="Antrags-ID",
                            value=f"> `{self.auszahlung_id}`\n> Versicherung: `{versicherung}`\n> [Zur Auszahlungsnachricht]({self.auszahlungs_link.value})",
                            inline=False,
                        )
                        ve.add_field(
                            name="Details",
                            value=f"> Verfügbar vorher: `{verfügbar:,.2f} €`\n> Ausgezahlt: `-{betrag:,.2f} €`\n> **Restguthaben: `{neues_guthaben:,.2f} €`**",
                            inline=False,
                        )
                        ve.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
                        await thread.send(embed=ve)
                except Exception as ex:
                    logger.error(f"Vermerk Fehler: {ex}")

            try:
                az_channel = self.guild.get_channel(pending["channel_id"])
                if az_channel:
                    orig_msg = await az_channel.fetch_message(pending["message_id"])
                    if orig_msg.embeds:
                        upd = orig_msg.embeds[0]
                        upd.color = COLOR_SUCCESS
                        for i, field in enumerate(upd.fields):
                            if field.name == "Status":
                                upd.set_field_at(
                                    i, name="Status", value="Genehmigt", inline=True
                                )
                                break
                        upd.add_field(
                            name="Genehmigt von",
                            value=f"{self.confirmer.mention}",
                            inline=True,
                        )
                        await orig_msg.edit(embed=upd, view=None)
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

            s = discord.Embed(
                title="Auszahlung bestätigt!",
                description=f"Auszahlung `{self.auszahlung_id}` genehmigt.",
                color=EMBED_COLOR,
            )
            s.add_field(name="Betrag", value=f"> `{betrag:,.2f} €`", inline=True)
            s.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
            await interaction.followup.send(embed=s, ephemeral=True)
        except Exception as e:
            logger.error(f"Bestätigen Fehler: {e}", exc_info=True)
            await interaction.followup.send(f" Fehler: {e}", ephemeral=True)


class AuszahlungActionView(discord.ui.View):
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
                embed=build_error_embed(
                    "Zugriff verweigert!",
                    "Nur das Firmenkonto kann Auszahlungsanträge bearbeiten.",
                    "Firmenkonto",
                ),
                ephemeral=True,
            )
            return
        az_id = self._get_az_id(interaction.message)
        pending = data.get("pending_auszahlungen", {}).get(az_id)
        if not pending or pending.get("status") != "ausstehend":
            await interaction.response.send_message(
                " Bereits bearbeitet oder nicht gefunden.", ephemeral=True
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
                embed=build_error_embed(
                    "Zugriff verweigert!", "Nur das Firmenkonto.", "Firmenkonto"
                ),
                ephemeral=True,
            )
            return
        az_id = self._get_az_id(interaction.message)
        pending = data.get("pending_auszahlungen", {}).get(az_id)
        if not pending or pending.get("status") != "ausstehend":
            await interaction.response.send_message(
                " Bereits bearbeitet.", ephemeral=True
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
            upd = interaction.message.embeds[0]
            upd.color = COLOR_ERROR
            for i, field in enumerate(upd.fields):
                if field.name == "Status":
                    upd.set_field_at(i, name="Status", value=" Abgelehnt", inline=True)
                    break
            upd.add_field(
                name="Abgelehnt von", value=f"{interaction.user.mention}", inline=True
            )
            await interaction.message.edit(embed=upd, view=None)
        except Exception as ex:
            logger.error(f"Update Fehler: {ex}")
        add_log_entry(
            "AUSZAHLUNG_ABGELEHNT", interaction.user.id, {"auszahlung_id": az_id}
        )
        await interaction.response.send_message(
            f" Antrag `{az_id}` wurde abgelehnt.", ephemeral=True
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
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
            ),
            ephemeral=True,
        )
        return
    if customer_id not in data["customers"]:
        await interaction.response.send_message(
            embed=build_error_embed(
                "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
            ),
            ephemeral=True,
        )
        return
    customer = data["customers"][customer_id]
    if not customer.get("versicherungen"):
        await interaction.response.send_message(
            " Keine Versicherungen vorhanden.", ephemeral=True
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
        embed=e, view=AuszahlungSelectView(customer_id, customer), ephemeral=True
    )


# ═══════════════════════════════════════════════════════
#   TICKET SYSTEM — PANELS
# ═══════════════════════════════════════════════════════
class KundenkontaktView(discord.ui.View):
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


class SchadensmeldungView(discord.ui.View):
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
class InaktivitätsWarnView(discord.ui.View):
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
                "Ticket-Daten nicht gefunden.", ephemeral=True
            )
            return

        # Berechtigung: Mitarbeiter ODER der Versicherungsnehmer
        customer = data["customers"].get(ticket_info.get("customer_id", ""), {})
        cust_discord_id = customer.get("discord_user_id")
        if not is_mitarbeiter(interaction) and interaction.user.id != cust_discord_id:
            await interaction.response.send_message(
                embed=build_error_embed(
                    "Zugriff verweigert!",
                    "Nur Mitarbeiter oder der Versicherungsnehmer können das abbrechen.",
                ),
                ephemeral=True,
            )
            return

        # Timer zurücksetzen
        data["ticket_channels"][ch_key]["inactivity_warned_at"] = None
        data["ticket_channels"][ch_key]["last_human_message"] = get_now().isoformat()
        save_data(data)

        button.disabled = True
        button.label = "Schließen abgebrochen"
        await interaction.response.edit_message(view=self)

        confirm = discord.Embed(
            title="Automatisches Schließen abgebrochen",
            description=f"> {interaction.user.mention} hat das automatische Schließen abgebrochen.\n> Das Ticket bleibt geöffnet.",
            color=EMBED_COLOR,
            timestamp=get_now(),
        )
        confirm.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
        await interaction.channel.send(embed=confirm)


# ═══════════════════════════════════════════════════════
#   TICKET VIEWS — MODERN DESIGN
# ═══════════════════════════════════════════════════════
class SchadensmeldungTicketView(discord.ui.View):
    """View für Schadensmeldungs-Tickets: Beanspruchen/Freigeben + Schließen."""

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
                embed=build_error_embed(
                    "Fehler!",
                    "Ticket-Daten nicht gefunden. Bitte wende dich an einen Administrator.",
                ),
                ephemeral=True,
            )
            return

        claimed_by = ticket_info.get("claimed_by")

        if claimed_by is None:
            # ── BEANSPRUCHEN ──
            if not is_mitarbeiter(interaction):
                await interaction.response.send_message(
                    embed=build_error_embed(
                        "Zugriff verweigert!",
                        "Nur Mitarbeiter können Tickets beanspruchen.",
                        "Mitarbeiter",
                    ),
                    ephemeral=True,
                )
                return

            data["ticket_channels"][channel_key]["claimed_by"] = interaction.user.id
            data["ticket_channels"][channel_key]["claimed_at"] = get_now().isoformat()
            save_data(data)

            # Sofort Buttons aktualisieren — bevor langsame API-Calls kommen
            button.label = "Freigeben"
            button.style = discord.ButtonStyle.secondary
            await interaction.response.edit_message(view=self)

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
                "Ticket beansprucht",
                f"> {interaction.user.mention} hat dieses Ticket übernommen.\n"
                f"> Andere Mitarbeiter haben keinen Schreibzugriff mehr.\n"
                f"> Freigeben über den Freigeben-Button.",
            )
            await interaction.channel.send(embed=claim_embed)
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
                    embed=build_error_embed(
                        "Zugriff verweigert!",
                        f"Nur der Beansprucher ({claimer_name}) oder die Leitungsebene kann freigeben.",
                    ),
                    ephemeral=True,
                )
                return

            old_claimer = interaction.guild.get_member(claimed_by)
            data["ticket_channels"][channel_key]["claimed_by"] = None
            save_data(data)

            # Sofort Buttons aktualisieren
            button.label = "Beanspruchen"
            button.style = discord.ButtonStyle.primary
            await interaction.response.edit_message(view=self)

            # Kanalberechtigungen wiederherstellen
            for role in _get_roles(interaction.guild, MITARBEITER_ROLE_ID):
                await interaction.channel.set_permissions(
                    role, read_messages=True, send_messages=True
                )
            if old_claimer:
                await interaction.channel.set_permissions(old_claimer, overwrite=None)

            release_embed = dvg_embed(
                "Ticket freigegeben",
                f"> {interaction.user.mention} hat das Ticket freigegeben.\n"
                f"> Alle Mitarbeiter haben wieder Schreibzugriff.",
            )
            await interaction.channel.send(embed=release_embed)
            add_log_entry(
                "TICKET_FREIGEGEBEN",
                interaction.user.id,
                {"channel_id": interaction.channel.id},
            )

    @discord.ui.button(
        label="Ticket schließen",
        style=discord.ButtonStyle.danger,
        custom_id="sd_close_ticket",
    )
    async def close_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not is_mitarbeiter(interaction):
            await interaction.response.send_message(
                embed=build_error_embed(
                    "Zugriff verweigert!",
                    "Nur Mitarbeiter können Tickets schließen.",
                    "Mitarbeiter",
                ),
                ephemeral=True,
            )
            return
        ch_key = str(interaction.channel.id)
        ticket_info = data.get("ticket_channels", {}).get(ch_key, {})
        await close_ticket_channel(interaction, interaction.channel, ticket_info)


class KundenkontaktTicketView(discord.ui.View):
    """View für Kundenkontakt-Tickets: Nur Schließen-Button."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Ticket schließen",
        style=discord.ButtonStyle.danger,
        custom_id="kk_close_ticket",
    )
    async def close_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not is_mitarbeiter(interaction):
            await interaction.response.send_message(
                embed=build_error_embed(
                    "Zugriff verweigert!",
                    "Nur Mitarbeiter können Tickets schließen.",
                    "Mitarbeiter",
                ),
                ephemeral=True,
            )
            return
        ch_key = str(interaction.channel.id)
        ticket_info = data.get("ticket_channels", {}).get(ch_key, {})
        await close_ticket_channel(interaction, interaction.channel, ticket_info)


# Legacy View — bleibt für vor dem Update erstellte Tickets
class TicketCloseView(discord.ui.View):
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
                embed=build_error_embed(
                    "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
                ),
                ephemeral=True,
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
                    embed=build_error_embed(
                        "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
                    ),
                    ephemeral=True,
                )
                return
            customer = data["customers"][customer_id]

            # ── Duplikat-Check: Mitarbeiter ──
            existing_ma = get_active_ticket(interaction.user.id, "kundenkontakt")
            if existing_ma:
                await interaction.followup.send(
                    embed=build_error_embed(
                        "Aktives Ticket vorhanden!",
                        f"Du hast bereits ein offenes Kundenkontakt-Ticket (<#{existing_ma}>).\nBitte schließe dieses zuerst.",
                    ),
                    ephemeral=True,
                )
                return

            # ── Duplikat-Check: Kunde ──
            existing_cust = customer_has_active_ticket(customer_id, "kundenkontakt")
            if existing_cust:
                await interaction.followup.send(
                    embed=build_error_embed(
                        "Ticket für diesen Kunden vorhanden!",
                        f"Für **{customer['rp_name']}** existiert bereits ein Kundenkontakt-Ticket (<#{existing_cust}>).",
                    ),
                    ephemeral=True,
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
                    embed=build_error_embed(
                        "Nicht konfiguriert!",
                        "Kundenkontakt-Kategorie nicht eingerichtet.",
                    ),
                    ephemeral=True,
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
            embed = discord.Embed(
                title="Kundenkontakt-Ticket", color=EMBED_COLOR, timestamp=get_now()
            )
            embed.add_field(
                name="Ticketinformationen",
                value=(
                    f"> Erstellt: `{get_now().strftime('%d.%m.%Y • %H:%M')}`\n"
                    f"> Kunden-ID: `{customer_id}`\n"
                    f"> Bearbeiter: {interaction.user.mention}"
                ),
                inline=False,
            )
            embed.add_field(
                name="Versicherungsnehmer",
                value=f"> RP-Name: **{customer['rp_name']}**\n> Discord: {customer_user.mention if customer_user else '`Unbekannt`'}",
                inline=False,
            )
            embed.add_field(
                name="Kontaktgrund",
                value=f"```{self.reason.value[:500]}```",
                inline=False,
            )
            ins_info = "\n".join(f"> - {ins}" for ins in customer["versicherungen"])
            embed.add_field(
                name="Versicherungsübersicht",
                value=f"{ins_info}\n> Monatsbeitrag: `{customer['total_monthly_price']:,.2f} €`",
                inline=False,
            )
            embed.add_field(
                name="Schreibrechte",
                value="> Leitungsebene + Ticketersteller können schreiben.\n> Andere Mitarbeiter haben Leserechte.",
                inline=False,
            )
            embed.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)

            mentions = [interaction.user.mention] + (
                [customer_user.mention] if customer_user else []
            )
            await ticket_channel.send(
                " ".join(mentions), embed=embed, view=KundenkontaktTicketView()
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

            s = discord.Embed(
                title="Ticket erstellt!",
                description=f"Kundenkontakt-Ticket: {ticket_channel.mention}",
                color=EMBED_COLOR,
            )
            await interaction.followup.send(embed=s, ephemeral=True)
        except Exception as e:
            logger.error(f"Ticket Fehler: {e}", exc_info=True)
            await interaction.followup.send(f"Fehler: {e}", ephemeral=True)


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
                    embed=build_error_embed(
                        "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
                    ),
                    ephemeral=True,
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
                await interaction.followup.send(embed=bl_e, ephemeral=True)
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
                    embed=build_error_embed(
                        "Aktive Schadensmeldung vorhanden!",
                        f"Für **{customer['rp_name']}** existiert bereits eine offene Schadensmeldung (<#{existing}>).\nBitte warte, bis diese bearbeitet wurde.",
                    ),
                    ephemeral=True,
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
                await interaction.followup.send(embed=fraud_e, ephemeral=True)
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
                    embed=build_error_embed(
                        "Nicht konfiguriert!",
                        "Schadensmeldungs-Kategorie nicht eingerichtet.",
                    ),
                    ephemeral=True,
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
                    f"> Kunde: **{customer['rp_name']}** (`{customer_id}`)\n"
                    f"> Eingereicht: {get_now().strftime('%d.%m.%Y, %H:%M Uhr')}"
                ),
                inline=False,
            )
            embed.add_field(
                name="Beteiligte Personen",
                value=f"> Geschädigter: **{self.Geschädigter.value}**\n> Täter: **{self.Täter.value}**",
                inline=False,
            )
            embed.add_field(
                name="Vorfallbeschreibung",
                value=f"```{self.beschreibung.value}```",
                inline=False,
            )
            embed.add_field(
                name="Nachweis / Rechnung", value=f"> `{nachweis_val}`", inline=False
            )
            embed.add_field(
                name="Bearbeitung",
                value="> Ticket mit **Beanspruchen** übernehmen.\n> Leitungsebene behält jederzeit Schreibrechte.",
                inline=False,
            )

            ma_ping = " ".join(r.mention for r in ma_roles) if ma_roles else ""
            await ticket_channel.send(
                f"{ma_ping} — Neue Schadensmeldung!",
                embed=embed,
                view=SchadensmeldungTicketView(),
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
                "Schadensmeldung eingereicht", f"> Ticket: {ticket_channel.mention}"
            )
            await interaction.followup.send(embed=s, ephemeral=True)
        except Exception as e:
            logger.error(f"Schadensmeldung Fehler: {e}")
            await interaction.followup.send(f"Fehler: {e}", ephemeral=True)


# ═══════════════════════════════════════════════════════
#   TICKET BEFEHLE — ADD / REMOVE
# ═══════════════════════════════════════════════════════
@bot.tree.command(name="add", description="Fügt eine Person zum aktuellen Ticket hinzu")
@app_commands.describe(user="Der User, der hinzugefügt werden soll")
async def add_user_to_ticket(interaction: discord.Interaction, user: discord.Member):
    if not is_mitarbeiter(interaction):
        await interaction.response.send_message(
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
            ),
            ephemeral=True,
        )
        return
    if not (
        interaction.channel.name.startswith("kontakt-")
        or interaction.channel.name.startswith("schaden-")
    ):
        await interaction.response.send_message(
            " Nur in Ticket-Channels nutzbar.", ephemeral=True
        )
        return
    await interaction.channel.set_permissions(
        user, read_messages=True, send_messages=True, read_message_history=True
    )
    e = discord.Embed(
        title="Person hinzugefügt!",
        description=f"> {interaction.user.mention} hat {user.mention} hinzugefügt.",
        color=EMBED_COLOR,
    )
    e.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
    await interaction.response.send_message(embed=e)


@bot.tree.command(
    name="remove", description="Entfernt eine Person vom aktuellen Ticket"
)
@app_commands.describe(user="Der User, der entfernt werden soll")
async def remove_user_from_ticket(
    interaction: discord.Interaction, user: discord.Member
):
    if not is_mitarbeiter(interaction):
        await interaction.response.send_message(
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
            ),
            ephemeral=True,
        )
        return
    if not (
        interaction.channel.name.startswith("kontakt-")
        or interaction.channel.name.startswith("schaden-")
    ):
        await interaction.response.send_message(
            " Nur in Ticket-Channels nutzbar.", ephemeral=True
        )
        return
    await interaction.channel.set_permissions(user, overwrite=None)
    e = discord.Embed(
        title="Person entfernt!",
        description=f"> {interaction.user.mention} hat {user.mention} entfernt.",
        color=EMBED_COLOR,
    )
    e.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
    await interaction.response.send_message(embed=e)


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
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur die Leitungsebene.", "Leitungsebene"
            ),
            ephemeral=True,
        )
        return
    await interaction.response.defer(ephemeral=True)
    try:
        if not data["logs"]:
            await interaction.followup.send(
                embed=dvg_embed("Keine Logs vorhanden!"), ephemeral=True
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
        embed = discord.Embed(
            title="Aktivitätsprotokoll",
            description=f"**Letzte {len(recent)} Aktivitäten**",
            color=EMBED_COLOR,
            timestamp=get_now(),
        )
        for log in recent:
            ts = make_aware(datetime.fromisoformat(log["timestamp"])).strftime(
                "%d.%m.%Y • %H:%M:%S"
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
            detail_str = "\n".join(f"> {p}" for p in parts[:3]) if parts else "> —"
            embed.add_field(
                name=f"{emoji} {display}",
                value=f"> **{ts}**\n> {user_name}\n{detail_str}",
                inline=False,
            )
        embed.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        logger.error(f"Logs Fehler: {e}", exc_info=True)
        await interaction.followup.send(
            embed=build_error_embed("Fehler!", str(e)), ephemeral=True
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
                embed=build_error_embed(
                    "Keine Akte gefunden!",
                    "Für Ihren Account wurde keine aktive Versicherungsakte gefunden.\nBitte wenden Sie sich an einen Mitarbeiter.",
                ),
                ephemeral=True,
            )
            return
        customer_id = found_id
    else:
        if not customer_id:
            await interaction.response.send_message(
                embed=build_error_embed(
                    "Fehlende Angabe!",
                    "Bitte geben Sie eine Versicherungsnehmer-ID an.",
                ),
                ephemeral=True,
            )
            return
        if customer_id not in data["customers"]:
            await interaction.response.send_message(
                embed=build_error_embed(
                    "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
                ),
                ephemeral=True,
            )
            return

    customer = data["customers"][customer_id]
    ins_types = get_insurance_types()
    embed = discord.Embed(
        title=f" Kundenakte — {customer['rp_name']}",
        color=EMBED_COLOR,
        timestamp=get_now(),
    )
    embed.add_field(
        name="Stammdaten",
        value=f"> Kunden-ID: `{customer_id}`\n> RP-Name: **{customer['rp_name']}**\n> Kartenzahlung: `{customer['hbpay_nummer']}`\n> Economy-ID: `{customer['economy_id']}`\n> Status: `{customer.get('status', 'aktiv')}`",
        inline=False,
    )

    auszahlungen = customer.get("auszahlungen", {})
    ins_text = ""
    for ins in customer.get("versicherungen", []):
        limit = ins_types.get(ins, {}).get("auszahlung_limit", 0.0)
        ausgezahlt = auszahlungen.get(ins, 0.0)
        bar_filled = int((ausgezahlt / limit * 10)) if limit > 0 else 0
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        ins_text += f"> **{ins}**\n> `{bar}` {ausgezahlt:,.0f} € / {limit:,.0f} €\n"
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
        value=f"> Offen: `{off_re}`\n> Bezahlt: `{bez_re}`\n> Monatsbeitrag: `{customer['total_monthly_price']:,.2f} €`",
        inline=False,
    )
    embed.add_field(
        name="Metadaten",
        value=f"> Angelegt: {make_aware(datetime.fromisoformat(customer['created_at'])).strftime('%d.%m.%Y • %H:%M Uhr')}\n> Discord: <@{customer['discord_user_id']}>",
        inline=False,
    )
    thread_id = customer.get("thread_id")
    if thread_id:
        embed.add_field(name="Akte", value=f"> <#{thread_id}>", inline=False)
    embed.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ═══════════════════════════════════════════════════════
#   STATISTIKEN
# ═══════════════════════════════════════════════════════
@bot.tree.command(
    name="statistiken", description="Zeigt eine Übersicht aller Bot-Statistiken"
)
async def show_stats(interaction: discord.Interaction):
    if not is_leitungsebene(interaction):
        await interaction.response.send_message(
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur die Leitungsebene.", "Leitungsebene"
            ),
            ephemeral=True,
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
        value=f"> Monatsbeiträge: **`{total_mb:,.2f} €`**\n> Ausgezahlt: `{total_az:,.2f} €`",
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
    embed.set_author(name=AUTHOR_NAME, icon_url=FOOTER_ICON)
    embed.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
    await interaction.response.send_message(embed=embed, ephemeral=True)


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
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
            ),
            ephemeral=True,
        )
        return
    if customer_id not in data["customers"]:
        await interaction.response.send_message(
            embed=build_error_embed(
                "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
            ),
            ephemeral=True,
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

    await interaction.response.send_message(embed=e, ephemeral=True)


# ═══════════════════════════════════════════════════════
#   PORTAL-ZUGANG
# ═══════════════════════════════════════════════════════
@bot.tree.command(
    name="portal-zugang",
    description="Sendet dem Kunden seinen persoenlichen Portal-Zugangscode per DM",
)
@app_commands.describe(customer_id="Versicherungsnehmer-ID")
@app_commands.autocomplete(customer_id=customer_id_autocomplete)
async def cmd_portal_zugang(interaction: discord.Interaction, customer_id: str):
    if not is_mitarbeiter(interaction):
        await interaction.response.send_message(
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
            ),
            ephemeral=True,
        )
        return
    if customer_id not in data["customers"]:
        await interaction.response.send_message(
            embed=build_error_embed(
                "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
            ),
            ephemeral=True,
        )
        return

    customer = data["customers"][customer_id]
    if customer.get("status") == "archiviert":
        await interaction.response.send_message(
            embed=build_error_embed(
                "Akte archiviert!",
                "Für archivierte Kunden kann kein Portal-Zugang ausgestellt werden.",
            ),
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    token = generate_portal_token(customer_id)
    portal_url = f"{BOT_BASE_URL}/portal/{token}" if BOT_BASE_URL else None
    member = interaction.guild.get_member(customer["discord_user_id"])

    if portal_url and member:
        dm_embed = dvg_embed(
            "Ihr DVG Kundenportal-Zugang",
            "> Ihr persoenlicher Zugangscode wurde erstellt.\n"
            "> Ueber den Button unten gelangen Sie direkt zu Ihrer Versicherungsübersicht.",
        )
        dm_embed.add_field(
            name="Versicherungsnehmer", value=f"> {customer['rp_name']}", inline=True
        )
        dm_embed.add_field(name="Kunden-ID", value=f"> `{customer_id}`", inline=True)
        dm_embed.add_field(
            name="Zugangscode",
            value=f"> ||`{token}`||\n> (Klicken zum Anzeigen — nicht weitergeben!)",
            inline=False,
        )
        link_view = discord.ui.View()
        link_view.add_item(discord.ui.Button(label="Zum Kundenportal", url=portal_url))
        try:
            await member.send(embed=dm_embed, view=link_view)
            dm_ok = True
        except discord.Forbidden:
            dm_ok = False
    else:
        dm_ok = False

    result = dvg_embed(
        "Portal-Zugang ausgestellt",
        f"> Zugangscode für **{customer['rp_name']}** generiert.",
    )
    result.add_field(name="Kunden-ID", value=f"> `{customer_id}`", inline=True)
    result.add_field(
        name="DM gesendet",
        value=f"> {'Ja' if dm_ok else 'Nein (DMs gesperrt)'}",
        inline=True,
    )
    if portal_url:
        result.add_field(name="Portal-URL", value=f"> {portal_url}", inline=False)
    else:
        result.add_field(
            name="Hinweis",
            value="> `BOT_BASE_URL` nicht gesetzt — kein Link generierbar.\n"
            "> Bitte Umgebungsvariable auf Render.com konfigurieren.",
            inline=False,
        )
    add_log_entry(
        "PORTAL_ZUGANG_AUSGESTELLT",
        interaction.user.id,
        {"customer_id": customer_id, "dm_gesendet": dm_ok},
    )
    await interaction.followup.send(embed=result, ephemeral=True)


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
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur die Leitungsebene.", "Leitungsebene"
            ),
            ephemeral=True,
        )
        return
    if customer_id not in data["customers"]:
        await interaction.response.send_message(
            embed=build_error_embed(
                "Nicht gefunden!", f"Keine Akte mit ID `{customer_id}`."
            ),
            ephemeral=True,
        )
        return
    if is_blacklisted(customer_id):
        await interaction.response.send_message(
            embed=dvg_embed(
                "Bereits gesperrt",
                f"> Kunden-ID `{customer_id}` ist bereits auf der Blacklist.",
            ),
            ephemeral=True,
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
    await interaction.response.send_message(embed=e, ephemeral=True)
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
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur die Leitungsebene.", "Leitungsebene"
            ),
            ephemeral=True,
        )
        return
    if not is_blacklisted(customer_id):
        await interaction.response.send_message(
            embed=dvg_embed(
                "Nicht gesperrt", f"> `{customer_id}` ist nicht auf der Blacklist."
            ),
            ephemeral=True,
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
    await interaction.response.send_message(embed=e, ephemeral=True)
    await send_to_log_channel(interaction.guild, e)
    add_log_entry("BLACKLIST_REMOVE", interaction.user.id, {"customer_id": customer_id})


@bot.tree.command(name="blacklist-liste", description="Zeigt alle gesperrten Kunden")
async def cmd_blacklist_liste(interaction: discord.Interaction):
    if not is_mitarbeiter(interaction):
        await interaction.response.send_message(
            embed=build_error_embed(
                "Zugriff verweigert!", "Nur Mitarbeiter.", "Mitarbeiter"
            ),
            ephemeral=True,
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
                    f"> Grund: {entry.get('grund', '—')}\n"
                    f"> Gesperrt: `{added}` von {adder.mention if adder else '—'}"
                ),
                inline=False,
            )
    await interaction.response.send_message(embed=e, ephemeral=True)


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
            value="> - `insurance_data.json`\n> - `bot_config.json`",
            inline=False,
        )
        e.add_field(
            name="Zeitstempel",
            value=f"> {get_now().strftime('%d.%m.%Y, %H:%M:%S Uhr')}",
            inline=False,
        )
        e.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
        for guild in bot.guilds:
            ch = guild.get_channel(config["log_channel_id"])
            if ch:
                buf = create_zip_buffer()
                file = discord.File(buf, filename=f"auto_backup_{ts}.zip")
                await ch.send(embed=e, file=file)
                break
    except Exception as ex:
        logger.error(f"Auto-Backup Fehler: {ex}", exc_info=True)


@tasks.loop(hours=12)
async def refresh_schadensmeldung_panel():
    """
    Aktualisiert die Bearbeitungszeit im Schadensmeldungs-Panel alle 12 Stunden.
    Bearbeitet die neueste Panel-Nachricht im konfigurierten Kanal.
    """
    try:
        sm_ch_id = config.get("schadensmeldung_channel_id")
        if not sm_ch_id:
            return

        sm_stats = [
            s
            for s in data.get("ticket_stats", [])
            if s.get("type") == "schadensmeldung" and s.get("duration_minutes")
        ]
        if not sm_stats:
            return  # Noch keine Daten — kein Update nötig

        avg_m = int(sum(s["duration_minutes"] for s in sm_stats) / len(sm_stats))
        h, m = divmod(avg_m, 60)
        avg_tx = f"`{h}h {m}min`" if h else f"`{m} Minuten`"
        bearbzeit = (
            f"> Voraussichtliche Bearbeitungszeit: {avg_tx}\n"
            f"> Basierend auf {len(sm_stats)} abgeschlossenen Vorgängen."
        )

        for guild in bot.guilds:
            ch = guild.get_channel(sm_ch_id)
            if not ch:
                continue
            # Letzte Bot-Nachricht im Panel-Kanal finden und Embed aktualisieren
            async for msg in ch.history(limit=20):
                if msg.author.id == bot.user.id and msg.embeds:
                    emb = msg.embeds[0]
                    # Bearbeitungszeit-Feld aktualisieren
                    new_fields = []
                    updated = False
                    for field in emb.fields:
                        if field.name == "Bearbeitungszeit":
                            new_fields.append(("Bearbeitungszeit", bearbzeit, False))
                            updated = True
                        else:
                            new_fields.append((field.name, field.value, field.inline))
                    if updated:
                        emb.clear_fields()
                        for name, value, inline in new_fields:
                            emb.add_field(name=name, value=value, inline=inline)
                        await msg.edit(embed=emb)
                        logger.info(
                            "Schadensmeldungs-Panel Bearbeitungszeit aktualisiert."
                        )
                    break
            break
    except Exception as ex:
        logger.error(f"Panel-Refresh Fehler: {ex}", exc_info=True)


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
        data["ticket_channels"][ch_key]["inactivity_warned_at"] = (
            None  # Timer zurücksetzen
        )
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
#   KEEP-ALIVE (Render.com)
# ═══════════════════════════════════════════════════════
from flask import Flask, request, redirect
from threading import Thread

app_flask = Flask("")


@app_flask.route("/")
def home():
    return "InsuranceGuard v4 läuft!"


@app_flask.route("/health")
def health():
    return {
        "status": "healthy",
        "bot": bot.user.name if bot.user else "starting",
        "version": "InsuranceGuard v4",
        "latency_ms": round(bot.latency * 1000) if bot.latency else None,
        "customers": len(data.get("customers", {})),
        "open_tickets": len(data.get("ticket_channels", {})),
        "timestamp": get_now().isoformat(),
    }


@app_flask.route("/transcript/<transcript_id>")
def serve_transcript(transcript_id: str):
    """Liefert das gespeicherte HTML-Transcript (Discord-Style Dashboard)."""
    # Nur alphanumerische Zeichen + Bindestriche erlaubt (UUID-Format)
    safe_id = "".join(c for c in transcript_id if c.isalnum() or c == "-")
    path = f"transcripts/{safe_id}.html"
    if not os.path.exists(path):
        return "<h1>Transcript nicht gefunden oder abgelaufen.</h1>", 404
    with open(path, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


# ═══════════════════════════════════════════════════════
#   KUNDEN-PORTAL — Helfer & Token-System
# ═══════════════════════════════════════════════════════
def generate_portal_token(customer_id: str) -> str:
    """Gibt vorhandenen Token zurück oder erstellt einen neuen."""
    if customer_id not in data["customers"]:
        return ""
    if not data["customers"][customer_id].get("portal_token"):
        data["customers"][customer_id]["portal_token"] = uuid.uuid4().hex
        save_data(data)
    return data["customers"][customer_id]["portal_token"]


def get_customer_by_token(token: str):
    """Sucht Kunden anhand des Portal-Tokens. Gibt (customer_id, customer) zurück."""
    clean = token.strip().lower()
    for cid, c in data["customers"].items():
        if c.get("portal_token", "").lower() == clean and c.get("status") == "aktiv":
            return cid, c
    return None, None


# ═══════════════════════════════════════════════════════
#   KUNDEN-PORTAL — CSS
# ═══════════════════════════════════════════════════════
_PORTAL_CSS = """
/* ── Reset & Tokens ──────────────────────────────────── */
:root {
  --blue:        #3D4EC5;
  --blue-light:  #5a6de8;
  --blue-dim:    #1e255c;
  --red:         #B82238;
  --bg:          #080c1a;
  --bg2:         #0d1225;
  --surface:     #111827;
  --surface2:    #161f35;
  --border:      #1e2d52;
  --border-light:#283660;
  --text:        #e8eaf6;
  --text-dim:    #a8b0cc;
  --muted:       #5a6585;
  --green:       #34d399;
  --green-dim:   #0d2e22;
  --amber:       #fbbf24;
  --amber-dim:   #2d1f06;
  --red-bright:  #f87171;
  --red-dim:     #2d0a0a;
  --radius:      12px;
  --radius-sm:   8px;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-size: 15px;
  line-height: 1.55;
  min-height: 100vh;
}
a { color: var(--blue-light); text-decoration: none; }

/* ── Layout ─────────────────────────────────────────── */
.layout { display: flex; min-height: 100vh; }

/* ── Sidebar ─────────────────────────────────────────── */
.sidebar {
  width: 240px;
  flex-shrink: 0;
  background: var(--bg2);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
}
.sidebar-logo {
  padding: 24px 20px 20px;
  border-bottom: 1px solid var(--border);
}
.sidebar-logo .wordmark {
  font-size: 20px;
  font-weight: 900;
  letter-spacing: -0.5px;
  color: var(--text);
}
.sidebar-logo .wordmark span { color: var(--blue-light); }
.sidebar-logo .tagline {
  font-size: 11px;
  color: var(--muted);
  margin-top: 3px;
  text-transform: uppercase;
  letter-spacing: 1px;
}
.sidebar-nav { padding: 12px 10px; flex: 1; }
.nav-section {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: var(--muted);
  padding: 12px 10px 6px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-weight: 500;
  color: var(--text-dim);
  cursor: pointer;
  transition: all .15s;
  border: none;
  background: none;
  width: 100%;
  text-align: left;
}
.nav-item:hover { background: var(--surface); color: var(--text); }
.nav-item.active {
  background: var(--blue-dim);
  color: var(--blue-light);
  font-weight: 600;
}
.nav-icon {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  opacity: .7;
}
.nav-item.active .nav-icon { opacity: 1; }
.nav-badge {
  margin-left: auto;
  background: var(--blue-dim);
  color: var(--blue-light);
  font-size: 11px;
  font-weight: 700;
  padding: 1px 7px;
  border-radius: 99px;
}
.nav-badge.red { background: var(--red-dim); color: var(--red-bright); }
.sidebar-footer {
  padding: 16px 20px;
  border-top: 1px solid var(--border);
  font-size: 11px;
  color: var(--muted);
  line-height: 1.6;
}

/* ── Main Content ────────────────────────────────────── */
.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.topbar {
  background: var(--bg2);
  border-bottom: 1px solid var(--border);
  padding: 14px 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 10;
  backdrop-filter: blur(10px);
}
.topbar-left { font-size: 16px; font-weight: 700; }
.topbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}
.topbar-time { font-size: 12px; color: var(--muted); }
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 6px var(--green);
  flex-shrink: 0;
}
.content { padding: 28px; max-width: 900px; }

/* ── Tab panels ──────────────────────────────────────── */
.tab-panel { display: none; }
.tab-panel.active { display: block; }

/* ── Page header ─────────────────────────────────────── */
.page-header {
  margin-bottom: 24px;
}
.page-title { font-size: 22px; font-weight: 800; }
.page-sub { font-size: 13px; color: var(--muted); margin-top: 3px; }

/* ── Hero card ───────────────────────────────────────── */
.hero {
  background: linear-gradient(135deg, #111827 0%, #151f3a 60%, #1a2550 100%);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  padding: 24px;
  margin-bottom: 20px;
  position: relative;
  overflow: hidden;
}
.hero::before {
  content: '';
  position: absolute;
  top: -60px; right: -60px;
  width: 200px; height: 200px;
  background: radial-gradient(circle, rgba(61,78,197,.25) 0%, transparent 70%);
  pointer-events: none;
}
.hero-inner { display: flex; align-items: center; gap: 18px; }
.hero-avatar {
  width: 60px; height: 60px;
  border-radius: 14px;
  background: linear-gradient(135deg, var(--blue), #7c8ef0);
  display: flex; align-items: center; justify-content: center;
  font-size: 22px; font-weight: 900; color: #fff;
  flex-shrink: 0;
  box-shadow: 0 4px 20px rgba(61,78,197,.4);
}
.hero-name { font-size: 20px; font-weight: 800; }
.hero-meta {
  display: flex;
  gap: 16px;
  margin-top: 6px;
  flex-wrap: wrap;
}
.hero-meta-item { font-size: 12px; color: var(--text-dim); }
.hero-meta-item code {
  background: var(--surface2);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  color: var(--blue-light);
}
.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: rgba(52,211,153,.1);
  border: 1px solid rgba(52,211,153,.25);
  color: var(--green);
  font-size: 11px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 99px;
  margin-top: 8px;
}

/* ── Stat cards ──────────────────────────────────────── */
.stats-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}
.stat-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px;
  position: relative;
  overflow: hidden;
}
.stat-card::after {
  content: '';
  position: absolute;
  bottom: 0; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, var(--blue), transparent);
}
.stat-val {
  font-size: 26px;
  font-weight: 900;
  line-height: 1;
  margin-bottom: 6px;
}
.stat-lbl {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 1px;
  text-transform: uppercase;
  color: var(--muted);
}
.stat-trend {
  font-size: 12px;
  color: var(--green);
  margin-top: 4px;
}

/* ── Section ─────────────────────────────────────────── */
.section { margin-bottom: 28px; }
.section-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 14px;
}

/* ── Data card ───────────────────────────────────────── */
.data-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  margin-bottom: 12px;
}
.data-card-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.data-card-title {
  font-size: 15px;
  font-weight: 700;
}
.data-card-body { padding: 20px; }
.data-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
.data-field-lbl {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: .8px;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 5px;
}
.data-field-val {
  font-size: 16px;
  font-weight: 700;
}
.data-field-val code {
  background: var(--surface2);
  border: 1px solid var(--border);
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 14px;
  color: var(--blue-light);
  font-weight: 600;
}

/* ── Insurance card ──────────────────────────────────── */
.ins-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  margin-bottom: 12px;
  transition: border-color .2s;
}
.ins-card:hover { border-color: var(--border-light); }
.ins-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
}
.ins-name { font-size: 15px; font-weight: 700; }
.ins-price { font-size: 13px; color: var(--text-dim); margin-top: 2px; }
.ins-limit-badge {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-dim);
  background: var(--surface2);
  border: 1px solid var(--border);
  padding: 4px 10px;
  border-radius: 6px;
  white-space: nowrap;
}
.progress-track {
  height: 6px;
  background: var(--bg);
  border-radius: 99px;
  overflow: hidden;
  margin-bottom: 10px;
}
.progress-fill {
  height: 100%;
  border-radius: 99px;
  background: linear-gradient(90deg, var(--blue), var(--blue-light));
  transition: width 1s cubic-bezier(.4,0,.2,1);
}
.progress-fill.warn  { background: linear-gradient(90deg, var(--amber), #f59e0b); }
.progress-fill.full  { background: linear-gradient(90deg, var(--red), #f87171); }
.progress-labels {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-dim);
}
.progress-labels strong { color: var(--text); }

/* ── Table ───────────────────────────────────────────── */
.table-wrap {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
table { width: 100%; border-collapse: collapse; font-size: 14px; }
thead th {
  text-align: left;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 1.2px;
  text-transform: uppercase;
  color: var(--muted);
  padding: 12px 16px;
  background: var(--surface2);
  border-bottom: 1px solid var(--border);
}
tbody tr { border-bottom: 1px solid var(--border); transition: background .1s; }
tbody tr:last-child { border-bottom: none; }
tbody tr:hover { background: var(--surface2); }
td { padding: 12px 16px; color: var(--text); vertical-align: middle; }
td code {
  background: var(--bg2);
  border: 1px solid var(--border);
  padding: 2px 7px;
  border-radius: 5px;
  font-size: 12px;
  color: var(--blue-light);
}

/* ── Badges ──────────────────────────────────────────── */
.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  border-radius: 99px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .3px;
  white-space: nowrap;
}
.badge-green  { background: var(--green-dim);  color: var(--green); }
.badge-amber  { background: var(--amber-dim);  color: var(--amber); }
.badge-red    { background: var(--red-dim);    color: var(--red-bright); }
.badge-blue   { background: var(--blue-dim);   color: var(--blue-light); }
.badge-dot {
  width: 5px; height: 5px;
  border-radius: 50%;
  background: currentColor;
}

/* ── Empty state ─────────────────────────────────────── */
.empty {
  text-align: center;
  padding: 48px 24px;
  color: var(--muted);
  font-size: 14px;
}
.empty-icon {
  font-size: 32px;
  margin-bottom: 12px;
  opacity: .4;
}

/* ── Responsive ──────────────────────────────────────── */
@media (max-width: 768px) {
  .sidebar { display: none; }
  .stats-row { grid-template-columns: 1fr 1fr; }
  .data-grid { grid-template-columns: 1fr; }
  .content { padding: 16px; }
  .hero-inner { flex-direction: column; align-items: flex-start; }
}
@media (max-width: 480px) {
  .stats-row { grid-template-columns: 1fr; }
}
"""

_LOGIN_CSS = """
:root{--blue:#3D4EC5;--bg:#0b0f1e;--card:#131929;--border:#232d50;
  --text:#e8eaf6;--muted:#8892b0;}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;
  min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px}
.card{background:var(--card);border:1px solid var(--border);border-radius:16px;
  padding:40px;width:100%;max-width:420px}
.logo{font-size:28px;font-weight:900;letter-spacing:-1px;margin-bottom:6px}
.logo span{color:var(--blue)}
.sub{color:var(--muted);font-size:14px;margin-bottom:28px}
label{font-size:13px;font-weight:600;color:var(--muted);display:block;margin-bottom:6px}
input{width:100%;background:#0b0f1e;border:1px solid var(--border);border-radius:8px;
  padding:12px 14px;color:var(--text);font-size:15px;outline:none;
  transition:border-color .15s}
input:focus{border-color:var(--blue)}
.btn{display:block;width:100%;margin-top:16px;padding:13px;
  background:var(--blue);color:#fff;font-size:15px;font-weight:700;
  border:none;border-radius:8px;cursor:pointer;transition:opacity .15s}
.btn:hover{opacity:.85}
.err{background:#2a0a0a;border:1px solid #5a1010;border-radius:8px;
  padding:12px;color:#f87171;font-size:13px;margin-bottom:16px}
.info{margin-top:24px;padding:14px;background:#0d1020;border-radius:8px;
  font-size:13px;color:var(--muted);line-height:1.6;border:1px solid var(--border)}
"""


# ═══════════════════════════════════════════════════════
#   KUNDEN-PORTAL — Dashboard HTML Builder
# ═══════════════════════════════════════════════════════
def build_portal_dashboard(customer_id: str, customer: dict, token: str) -> str:
    ins_types = get_insurance_types()
    auszahlungen = customer.get("auszahlungen", {})
    vers = customer.get("versicherungen", [])
    invoices = sorted(
        [
            (iid, inv)
            for iid, inv in data["invoices"].items()
            if inv.get("customer_id") == customer_id
        ],
        key=lambda x: x[1].get("created_at", ""),
        reverse=True,
    )
    schaden = sorted(
        data.get("schaden_historie", {}).get(customer_id, []),
        key=lambda x: x.get("datum", ""),
        reverse=True,
    )
    initials = "".join(w[0].upper() for w in customer.get("rp_name", "?").split()[:2])

    total_limit = sum(ins_types.get(i, {}).get("auszahlung_limit", 0.0) for i in vers)
    total_paid = sum(auszahlungen.get(i, 0.0) for i in vers)
    total_avail = max(0.0, total_limit - total_paid)
    pct_used = min(100, int(total_paid / total_limit * 100)) if total_limit > 0 else 0
    open_inv = sum(1 for _, inv in invoices if not inv.get("paid"))
    since = (
        make_aware(datetime.fromisoformat(customer["created_at"])).strftime("%d.%m.%Y")
        if customer.get("created_at")
        else "—"
    )

    # Pre-compute conditional HTML fragments (avoid complex f-string nesting)
    inv_badge_cls = "nav-badge red" if open_inv > 0 else "nav-badge"
    open_inv_style = 'style="color:var(--amber)"' if open_inv > 0 else ""
    pct_bar_cls = "progress-fill warn" if pct_used >= 60 else "progress-fill"

    # ── Insurance cards ───────────────────────────────────────────────────────
    ins_html = ""
    for ins in vers:
        limit = ins_types.get(ins, {}).get("auszahlung_limit", 0.0)
        price = ins_types.get(ins, {}).get("price", 0.0)
        ausgezahlt = auszahlungen.get(ins, 0.0)
        verfügbar = max(0.0, limit - ausgezahlt)
        pct = min(100, int(ausgezahlt / limit * 100)) if limit > 0 else 0
        bar_cls = (
            "progress-fill full"
            if pct >= 90
            else ("progress-fill warn" if pct >= 60 else "progress-fill")
        )
        avail_style = 'style="color:var(--red-bright)"' if pct >= 90 else ""
        ins_html += f"""
        <div class="ins-card">
          <div class="ins-header">
            <div>
              <div class="ins-name">{_esc(ins)}</div>
              <div class="ins-price">{price:,.2f} EUR / Monat</div>
            </div>
            <div class="ins-limit-badge">Limit: {limit:,.0f} EUR</div>
          </div>
          <div class="progress-track">
            <div class="{bar_cls}" style="width:{pct}%"></div>
          </div>
          <div class="progress-labels">
            <span>Ausgezahlt: <strong>{ausgezahlt:,.2f} EUR</strong></span>
            <span {avail_style}>Verfügbar: <strong>{verfügbar:,.2f} EUR</strong></span>
          </div>
        </div>"""

    if not ins_html:
        ins_html = '<div class="empty"><div class="empty-icon">*</div>Keine aktiven Versicherungen.</div>'

    # ── Invoice table ─────────────────────────────────────────────────────────
    if not invoices:
        inv_html = '<div class="empty"><div class="empty-icon">-</div>Keine Rechnungen vorhanden.</div>'
    else:
        rows = ""
        for iid, inv in invoices[:25]:
            try:
                due_dt = make_aware(datetime.fromisoformat(inv["due_date"]))
                due = due_dt.strftime("%d.%m.%Y")
            except Exception:
                due_dt = get_now()
                due = "—"
            if inv.get("paid"):
                badge = '<span class="badge badge-green"><span class="badge-dot"></span>Bezahlt</span>'
            elif due_dt < get_now():
                badge = '<span class="badge badge-red"><span class="badge-dot"></span>Ueberfällig</span>'
            else:
                badge = '<span class="badge badge-amber"><span class="badge-dot"></span>Ausstehend</span>'
            mahn = inv.get("reminder_count", 0)
            mahn_tx = (
                f' <span class="badge badge-red">Mahnstufe {mahn}</span>'
                if mahn > 0
                else ""
            )
            rows += f"""<tr>
              <td><code>{_esc(iid)}</code></td>
              <td style="font-weight:700">{inv.get("betrag", 0):,.2f} EUR</td>
              <td>{due}</td>
              <td>{badge}{mahn_tx}</td>
            </tr>"""
        inv_html = f"""<div class="table-wrap"><table>
          <thead><tr><th>Rechnungsnr.</th><th>Betrag</th><th>Fällig am</th><th>Status</th></tr></thead>
          <tbody>{rows}</tbody></table></div>"""

    # ── Damage history ────────────────────────────────────────────────────────
    if not schaden:
        sch_html = '<div class="empty"><div class="empty-icon">-</div>Keine Schadensmeldungen vorhanden.</div>'
    else:
        rows = ""
        for entry in schaden[:15]:
            try:
                datum = make_aware(datetime.fromisoformat(entry["datum"])).strftime(
                    "%d.%m.%Y"
                )
            except Exception:
                datum = "—"
            badge = (
                '<span class="badge badge-green"><span class="badge-dot"></span>Abgeschlossen</span>'
                if entry.get("status") == "abgeschlossen"
                else '<span class="badge badge-amber"><span class="badge-dot"></span>In Bearbeitung</span>'
            )
            rows += f"""<tr>
              <td><code>{_esc(entry.get("id", "—"))}</code></td>
              <td>{datum}</td>
              <td>{_esc(entry.get("Geschädigter", "—"))}</td>
              <td>{_esc(entry.get("Täter", "—"))}</td>
              <td>{badge}</td>
            </tr>"""
        sch_html = f"""<div class="table-wrap"><table>
          <thead><tr><th>Vorgang-Nr.</th><th>Datum</th><th>Geschädigter</th><th>Täter</th><th>Status</th></tr></thead>
          <tbody>{rows}</tbody></table></div>"""

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DVG Kundenportal &ndash; {_esc(customer["rp_name"])}</title>
<style>{_PORTAL_CSS}</style>
</head>
<body>
<div class="layout">
  <aside class="sidebar">
    <div class="sidebar-logo">
      <div class="wordmark">D<span>V</span>G</div>
      <div class="tagline">Kundenportal</div>
    </div>
    <nav class="sidebar-nav">
      <div class="nav-section">Navigation</div>
      <button class="nav-item active" onclick="showTab('Übersicht',this)">
        <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
          <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
        </svg>Übersicht
      </button>
      <button class="nav-item" onclick="showTab('vers',this)">
        <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        </svg>Versicherungen<span class="nav-badge">{len(vers)}</span>
      </button>
      <button class="nav-item" onclick="showTab('inv',this)">
        <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
        </svg>Rechnungen
        <span class="{inv_badge_cls}">{len(invoices)}</span>
      </button>
      <button class="nav-item" onclick="showTab('sch',this)">
        <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>Schadenhistorie<span class="nav-badge">{len(schaden)}</span>
      </button>
    </nav>
    <div class="sidebar-footer">
      InsuranceGuard v4<br>Copyright &copy; DVG<br>
      Stand: {get_now().strftime("%d.%m.%Y %H:%M")} Uhr
    </div>
  </aside>

  <div class="main">
    <header class="topbar">
      <div class="topbar-left">Guten Tag, {_esc(customer["rp_name"].split()[0])}</div>
      <div class="topbar-right">
        <div class="status-dot"></div>
        <span class="topbar-time">{get_now().strftime("%d.%m.%Y %H:%M")} Uhr</span>
      </div>
    </header>

    <div class="content">

      <div id="tab-Übersicht" class="tab-panel active">
        <div class="hero">
          <div class="hero-inner">
            <div class="hero-avatar">{_esc(initials)}</div>
            <div>
              <div class="hero-name">{_esc(customer["rp_name"])}</div>
              <div class="hero-meta">
                <span class="hero-meta-item">ID: <code>{_esc(customer_id)}</code></span>
                <span class="hero-meta-item">Kunde seit: <code>{since}</code></span>
                <span class="hero-meta-item">HBpay: <code>{_esc(customer.get("hbpay_nummer", "—"))}</code></span>
              </div>
              <div class="hero-badge">
                <span class="badge-dot"></span> Aktiver Versicherungsnehmer
              </div>
            </div>
          </div>
        </div>

        <div class="stats-row">
          <div class="stat-card">
            <div class="stat-val">{len(vers)}</div>
            <div class="stat-lbl">Versicherungen</div>
            <div class="stat-trend">Alle aktiv</div>
          </div>
          <div class="stat-card">
            <div class="stat-val">{customer.get("total_monthly_price", 0):,.0f} EUR</div>
            <div class="stat-lbl">Monatsbeitrag</div>
          </div>
          <div class="stat-card">
            <div class="stat-val" {open_inv_style}>
              {open_inv}
            </div>
            <div class="stat-lbl">Offene Rechnungen</div>
          </div>
        </div>

        <div class="section">
          <div class="section-label">Zahlungsdaten</div>
          <div class="data-card">
            <div class="data-card-body">
              <div class="data-grid">
                <div>
                  <div class="data-field-lbl">HBpay Kontonummer</div>
                  <div class="data-field-val"><code>{_esc(customer.get("hbpay_nummer", "—"))}</code></div>
                </div>
                <div>
                  <div class="data-field-lbl">Economy-ID</div>
                  <div class="data-field-val"><code>{_esc(customer.get("economy_id", "—"))}</code></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="section">
          <div class="section-label">Gesamtes Auszahlungslimit</div>
          <div class="data-card">
            <div class="data-card-body">
              <div class="data-grid">
                <div>
                  <div class="data-field-lbl">Limit gesamt</div>
                  <div class="data-field-val">{total_limit:,.2f} EUR</div>
                </div>
                <div>
                  <div class="data-field-lbl">Bereits ausgezahlt</div>
                  <div class="data-field-val">{total_paid:,.2f} EUR</div>
                </div>
              </div>
              <div style="margin-top:20px">
                <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--muted);margin-bottom:8px">
                  <span>Verbrauchtes Limit</span><span>{pct_used} %</span>
                </div>
                <div class="progress-track" style="height:8px">
                  <div class="progress-fill" style="width:{pct_used}%"></div>
                </div>
                <div style="font-size:12px;color:var(--muted);margin-top:6px">
                  {total_avail:,.2f} EUR verbleibend
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div id="tab-vers" class="tab-panel">
        <div class="page-header">
          <div class="page-title">Versicherungen</div>
          <div class="page-sub">{len(vers)} aktive{"r" if len(vers) == 1 else ""} Versicherungsvertrag{"" if len(vers) == 1 else "e"}</div>
        </div>
        {ins_html}
      </div>

      <div id="tab-inv" class="tab-panel">
        <div class="page-header">
          <div class="page-title">Rechnungen</div>
          <div class="page-sub">{len(invoices)} Rechnungen — {open_inv} offen</div>
        </div>
        {inv_html}
      </div>

      <div id="tab-sch" class="tab-panel">
        <div class="page-header">
          <div class="page-title">Schadenhistorie</div>
          <div class="page-sub">{len(schaden)} Schadensmeldung{"" if len(schaden) == 1 else "en"}</div>
        </div>
        {sch_html}
      </div>

    </div>
  </div>
</div>

<script>
function showTab(id,el){{
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(b=>b.classList.remove('active'));
  document.getElementById('tab-'+id).classList.add('active');
  el.classList.add('active');
}}
window.addEventListener('load',()=>{{
  document.querySelectorAll('.progress-fill').forEach(b=>{{
    const w=b.style.width;b.style.width='0%';
    setTimeout(()=>{{b.style.width=w;}},120);
  }});
}});
</script>
</body></html>"""


# ═══════════════════════════════════════════════════════
#   KUNDEN-PORTAL — Flask-Routen
# ═══════════════════════════════════════════════════════
@app_flask.route("/portal")
def portal_landing():
    err = ""
    if request.args.get("error"):
        err = '<div class="err">Ungultiger oder abgelaufener Zugangscode.</div>'
    html = f"""<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DVG Kundenportal</title><style>{_LOGIN_CSS}</style></head>
<body>
<div class="card">
  <div class="logo">D<span>V</span>G</div>
  <div class="sub">Kundenportal &ndash; Ihre Versicherungsübersicht</div>
  {err}
  <form method="POST" action="/portal/login">
    <label>Zugangscode</label>
    <input type="text" name="token" placeholder="Ihr persoenlicher Zugangscode" autofocus>
    <button class="btn" type="submit">Zum Portal</button>
  </form>
  <div class="info">
    Ihren Zugangscode erhalten Sie von einem DVG-Mitarbeiter per Direktnachricht im Discord-Server.
  </div>
</div>
</body></html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app_flask.route("/portal/login", methods=["POST"])
def portal_login():
    token = request.form.get("token", "").strip().lower()
    cid, _ = get_customer_by_token(token)
    if not cid:
        return redirect("/portal?error=1")
    return redirect(f"/portal/{token}")


@app_flask.route("/portal/<token>")
def portal_dashboard_route(token: str):
    cid, customer = get_customer_by_token(token.lower())
    if not cid:
        return redirect("/portal?error=1")
    return (
        build_portal_dashboard(cid, customer, token),
        200,
        {"Content-Type": "text/html; charset=utf-8"},
    )


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app_flask.run(host="0.0.0.0", port=port, use_reloader=False)


def keep_alive():
    t = Thread(target=run_flask, daemon=True)
    t.start()


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
