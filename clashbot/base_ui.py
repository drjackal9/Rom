import secrets as pysecrets

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from . import base_packs, bases, render, ttl
from .handlers import (can_manage, clan_for, clan_locale, edit_or_log, in_columns, services,
                       user_locale)

DRAFT_TTL = ttl.ONBOARD_TTL
SCOPES = ("clan", "library", "packs")
VILLAGES = ("home", "builder")
QUEUE = "bases_new"
PICKED = "✓ "


def scope_row(L, scope):
    return [InlineKeyboardButton((PICKED if scope == key else "") + L.t(f"bases.tab.{key}"),
                                 callback_data=f"bs:s:{key}") for key in SCOPES]


def pack_row(L, row):
    return [InlineKeyboardButton(
        f"{base_packs.pack_title(L, row)} · {row['n']}",
        callback_data=f"bs:im:{row['clan_alias']}:{row['village']}:{row['label']}")]


def hub_keyboard(L, rows, levels, scope, village, hall, manage, clan_alias):
    buttons = [scope_row(L, scope)]
    if scope == "packs":
        buttons += [pack_row(L, row) for row in rows]
        buttons.append([InlineKeyboardButton(L.t("menu.back"), callback_data="v:menu")])
        return InlineKeyboardMarkup(buttons)
    buttons.append([InlineKeyboardButton((PICKED if village == key else "")
                                         + L.t(f"bases.village.{key}"),
                                         callback_data=f"bs:v:{scope}:{key}") for key in VILLAGES])
    if levels:
        buttons += in_columns([InlineKeyboardButton(
            (PICKED if hall == level else "") + bases.hall_name(village, level),
            callback_data=f"bs:h:{scope}:{village}:{level}") for level in levels])
    for row in rows:
        buttons.append([InlineKeyboardButton(
            f"{bases.label_name(L, row['label'])} {bases.hall_name(row['village'], row['hall'])}",
            url=bases.link_url(L, row["id"]))])
        if manage and row.get("clan_alias") == clan_alias:
            buttons.append([
                InlineKeyboardButton(L.t("bases.btn_share"), callback_data=f"bs:sh:{row['alias']}"),
                InlineKeyboardButton(L.t("bases.btn_publish"),
                                     callback_data=f"bs:pb:{row['village']}:{row['label']}"),
                InlineKeyboardButton(L.t("bases.btn_remove"), callback_data=f"bs:rm:{row['alias']}"),
            ])
    buttons.append([InlineKeyboardButton(L.t("menu.back"), callback_data="v:menu")])
    return InlineKeyboardMarkup(buttons)


async def rows_for(store, clan, scope, village, hall):
    if scope == "packs":
        return await store.base_packs(bases.PAGE)
    if scope == "library":
        return await store.shared_bases(village, hall, bases.PAGE)
    return await base_packs.winner_first(
        store, clan.alias, await store.clan_bases(clan.alias, village, hall, bases.PAGE),
        village, hall)


async def hub_text(store, L, rows, scope, village, hall):
    if scope != "packs":
        return bases.card(L, rows, scope, village, hall)
    names = {}
    for row in rows:
        owner = await store.clan_by_alias(row["clan_alias"])
        names[row["clan_alias"]] = owner.name if owner else None
    return base_packs.pack_card(L, rows, names)


async def hub_view(update, context, clan, scope="clan", village="home", hall=None):
    store, _ = services(context)
    L, _ = await clan_locale(store, clan)
    rows = await rows_for(store, clan, scope, village, hall)
    whole = rows if hall is None else await rows_for(store, clan, scope, village, None)
    manage = update is not None and await can_manage(update, context, clan)
    return (await hub_text(store, L, rows, scope, village, hall),
            hub_keyboard(L, rows, bases.halls(whole, village), scope, village, hall, manage,
                         clan.alias))


async def open_hub(update, context, clan, query, scope="clan", village="home", hall=None):
    text, keyboard = await hub_view(update, context, clan, scope, village, hall)
    await edit_or_log(query, text, keyboard, clan.alias)


async def cmd_base(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store, _ = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await update.effective_message.reply_text(render.not_linked_view(user_locale(update)))
        return
    L, _ = await clan_locale(store, clan)
    layout = bases.parse_link(" ".join(context.args or []))
    if not layout:
        await update.effective_message.reply_text(
            render.card("🏰", L.t("bases.title"), L.t("bases.ask_link")))
        return
    code = pysecrets.token_hex(3)
    await store.kv_set(f"basedraft:{code}",
                       {"layout": layout, "user": update.effective_user.id,
                        "name": update.effective_user.first_name},
                       ref=clan.alias, ttl=DRAFT_TTL)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(
        bases.label_name(L, label), callback_data=f"bs:l:{code}:{label}")] for label in bases.LABELS])
    body = L.t("bases.ask_label", village=L.t(f"bases.village.{layout['village']}"),
               hall=bases.hall_name(layout["village"], layout["hall"]))
    await update.effective_message.reply_text(render.card("🏰", L.t("bases.title"), body),
                                              reply_markup=keyboard)


async def save_draft(update, context, clan, code, label):
    store, _ = services(context)
    L, _ = await clan_locale(store, clan)
    draft = await store.kv_get(f"basedraft:{code}")
    if not draft or label not in bases.LABELS:
        return L.t("bases.expired")
    layout = draft["layout"]
    alias = await store.add_base(clan.alias, layout, label,
                                 {"name": draft.get("name"), "by": draft.get("user")})
    await store.kv_del(f"basedraft:{code}")
    if not alias:
        return L.t("bases.duplicate")
    queued = await store.get_state(clan.alias, QUEUE) or []
    queued.append({"name": draft.get("name"), "village": layout["village"],
                   "hall": layout["hall"], "label": label})
    await store.set_state(clan.alias, QUEUE, queued)
    return L.t("bases.saved")


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    store, _ = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await query.answer()
        return
    L, _ = await clan_locale(store, clan)
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    if action == "s":
        await query.answer()
        await open_hub(update, context, clan, query, parts[2])
        return
    if action == "v":
        await query.answer()
        await open_hub(update, context, clan, query, parts[2], parts[3])
        return
    if action == "h":
        await query.answer()
        await open_hub(update, context, clan, query, parts[2], parts[3], int(parts[4]))
        return
    if action == "l":
        await query.answer(await save_draft(update, context, clan, parts[2], parts[3]))
        await open_hub(update, context, clan, query)
        return
    if action == "im":
        if not await can_manage(update, context, clan):
            await query.answer(L.t("h.admin_only"), show_alert=True)
            return
        copied = await base_packs.import_pack(store, clan, parts[2], parts[3], parts[4])
        await query.answer(L.t("bases.imported", n=copied) if copied
                           else L.t("bases.packs.empty"))
        await open_hub(update, context, clan, query, "packs")
        return
    if action == "pb":
        if not await base_packs.is_verified(store, update.effective_user.id, clan):
            await query.answer(L.t("bases.only_verified"), show_alert=True)
            return
        await query.answer(L.t("bases.published",
                               n=await base_packs.publish(store, clan, parts[2], parts[3])))
        await open_hub(update, context, clan, query)
        return
    if action in ("sh", "rm"):
        if not await can_manage(update, context, clan):
            await query.answer(L.t("h.admin_only"), show_alert=True)
            return
        row = await store.base_by_alias(parts[2])
        if not row or row["clan_alias"] != clan.alias:
            await query.answer(L.t("bases.expired"))
        elif action == "rm":
            await store.remove_base(row["alias"])
            await query.answer(L.t("bases.removed"))
        else:
            await store.set_base_flags(row["alias"], shared=not row["shared"])
            await query.answer(L.t("bases.shared"))
        await open_hub(update, context, clan, query)
        return
    await query.answer()
