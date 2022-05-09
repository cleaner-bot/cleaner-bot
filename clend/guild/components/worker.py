import logging
import typing

import hikari
import lupa  # type: ignore

from cleaner_i18n.translate import Message

from ..guild import CleanerGuild
from ..helper import action_delete, action_challenge, is_moderator, announcement
from ...shared.event import IGuildEvent, ILog


logger = logging.getLogger(__name__)
LUA_WHITELIST = {
    "_G",
    "_VERSION",
    "assert",
    "error",
    "getmetatable",
    "ipairs",
    "load",
    "math",
    "next",
    "pairs",
    "pcall",
    "rawequal",
    "rawget",
    "rawlen",
    "rawset",
    "require",
    "select",
    "setmetatable",
    "string",
    "table",
    "tonumber",
    "tostring",
    "type",
    "xpcall",
}
LUA_BOOT = """
local debug_sethook = debug.sethook
local coroutine = coroutine
local error = error
local setmetatable = setmetatable
local unpack = unpack or table.unpack
local script, cycle_limit
local function safe_call(fn, ...)
    if cycle_limit == nil then
        error("no cycle limit, call set_cycle_limit")
    end
    local coro = coroutine.create(fn)
    local limit_exceeded = false
    debug_sethook(coro, function()
        limit_exceeded = true
        debug_sethook(function() error("reached cycle limit") end, "cr", 1)
        error("reached cycle limit")
    end, "", cycle_limit)
    local result = {coroutine.resume(coro, ...)}
    if limit_exceeded then
        error("reached cycle limit")
    end
    for _, v in pairs(result) do
        if type(v) == "type" then
            setmetatable(v, {})
        end
    end
    if not result[1] then
        error(unpack(result, 2))
    end
    return unpack(result, 2)
end
return {
    set_cycle_limit = function(limit)
        cycle_limit = limit
    end,
    set_script = function(source)
        local fn, err = load(source, "<worker>", "t")
        if fn == nil then
            error(err)
        end
        script = safe_call(fn)
    end,
    call = function(...)
        return safe_call(script, ...)
    end,
}
"""


def _raise_error(*_):
    raise AttributeError("access denied")


def prepare_runtime(
    guild_id: int, source: str, max_memory: int, max_cycles: int
) -> tuple[lupa.LuaRuntime, typing.Any] | None:
    lua = lupa.LuaRuntime(
        unpack_returned_tuples=True,
        register_eval=False,
        register_builtins=False,
        attribute_handlers=(_raise_error, _raise_error),
        max_memory=max_memory,
    )
    boot = lua.execute(LUA_BOOT)
    lua_globals = lua.globals()
    for key in tuple(lua_globals):
        if key not in LUA_WHITELIST:
            del lua_globals[key]

    try:
        boot.set_cycle_limit(max_cycles)
        boot.set_script(source)
    except lupa.LuaError as e:
        logger.warning(f"error during booting worker {guild_id}", exc_info=e)
        return None

    return lua, boot


def on_message_create(event: hikari.GuildMessageCreateEvent, cguild: CleanerGuild):
    data = cguild.get_data()
    if (
        event.member is None
        or data is None
        or not data.config.workers_enabled
        or not data.entitlements.workers
        or is_moderator(cguild, event.member)
    ):
        return

    worker = cguild.worker
    spec = (
        data.worker.source,
        data.entitlements.workers_cpu,
        data.entitlements.workers_ram,
    )
    if worker is None or spec != cguild.worker_spec:
        worker = cguild.worker = prepare_runtime(
            event.guild_id,
            data.worker.source,
            data.entitlements.workers_ram,
            data.entitlements.workers_cpu,
        )
        if worker is None:
            # temporarily disable workers because they don't work
            data.config.workers_enabled = False
            if not data.config.logging_enabled:
                return
            return [
                ILog(
                    event.guild_id,
                    Message("components_worker_disable"),
                    event.message_id.created_at,
                )
            ]

        cguild.worker_spec = spec

    lua, boot = worker

    guild = event.get_guild()
    if guild is None:
        return

    permissions = 0
    for role in event.member.get_roles():
        permissions |= role.permissions

    lua_event = lua.table_from(
        {
            "message_id": str(event.message_id),
            "channel_id": str(event.channel_id),
            "guild_id": str(event.guild_id),
            "member_id": str(event.author_id),
            "member_roles": lua.table_from(map(str, event.member.role_ids)),
            "member_is_bot": event.is_bot,
            "member_permissions": str(permissions),
            "member_is_owner": event.author_id == guild.owner_id,
            "content": event.content,
            "attachments": lua.table_from(
                [
                    lua.table_from(
                        {
                            "attachment_id": str(a.id),
                            "filename": a.filename,
                            # "description": a.description,
                            "content_type": a.media_type,
                            "size": a.size,
                            "url": a.url,
                            "proxy_url": a.proxy_url,
                            "height": a.height,
                            "width": a.width,
                        }
                    )
                    for a in event.message.attachments
                ]
            ),
            "embeds": lua.table_from(
                [
                    lua.table_from(
                        {
                            "title": e.title,
                            "description": e.description,
                            "url": e.url,
                            "timestamp": e.timestamp,
                            "color": e.color,
                            "footer_text": e.footer and e.footer.text,
                            "footer_icon": (
                                e.footer and e.footer.icon and e.footer.icon.url
                            ),
                            "image_url": e.image and e.image.url,
                            "image_height": e.image and e.image.height,
                            "image_width": e.image and e.image.width,
                            "thumbnail_url": e.thumbnail and e.thumbnail.url,
                            "thumbnail_height": e.thumbnail and e.thumbnail.height,
                            "thumbnail_width": e.thumbnail and e.thumbnail.width,
                            "video_url": e.video and e.video.url,
                            "video_height": e.video and e.video.height,
                            "video_width": e.video and e.video.width,
                            "provider_name": e.provider and e.provider.name,
                            "provider_url": e.provider and e.provider.url,
                            "author_name": e.author and e.author.name,
                            "author_url": e.author and e.author.url,
                            "author_icon": (
                                e.author and e.author.icon and e.author.icon.url,
                            ),
                            "fields": [
                                {
                                    "name": f.name,
                                    "value": f.value,
                                    "inline": f.is_inline,
                                }
                                for f in e.fields
                            ],
                        }
                    )
                    for e in event.message.embeds
                ]
            ),
            "message_type": int(event.message.type),
            "application_id": (
                str(event.message.application_id)
                if event.message.application_id
                else None
            ),
            "mention_everyone": event.message.mentions.everyone,
            "mention_users": lua.table_from(
                map(str, event.message.mentions.user_ids)
                if event.message.mentions.user_ids
                else []
            ),
            "mention_roles": lua.table_from(
                map(str, event.message.mentions.role_ids)
                if event.message.mentions.role_ids
                else []
            ),
            "mention_channels": lua.table_from(
                map(
                    str,
                    event.message.mentions.channels_ids
                    if event.message.mentions.channels_ids
                    else [],
                )
            ),
            "interaction": event.message.interaction
            and lua.table_from(
                {
                    "id": str(event.message.interaction.id),
                    "type": int(event.message.interaction.type),
                    "name": event.message.interaction.name,
                    "user_id": str(event.message.interaction.user.id),
                }
            ),
        }
    )

    try:
        result = boot.call(lua_event)

        if lupa.lua_type(result) not in (None, "table"):
            raise lupa.LuaError("expected table or nil as return type")
    except lupa.LuaError as e:
        if not data.config.logging_enabled:
            return
        err = ":".join(e.args[0].split(":")[2:])[1:]
        return [
            ILog(
                event.guild_id,
                Message("components_worker_error", {"error": err}),
                event.message_id.created_at,
            )
        ]

    if result is None:
        return

    actions: list[IGuildEvent] = []
    info = {"rule": "worker", "guild": event.guild_id}
    for i in range(len(result)):
        action = result[i + 1]
        if not isinstance(action, str):
            continue
        name = action.split(":")[0]
        reason = action[len(name) + 1 :][:500]
        if name == "delete":
            actions.append(
                action_delete(
                    event.member,
                    event.message,
                    reason=Message("components_worker_reason", {"reason": reason}),
                    info=info,
                )
            )
        elif name == "block":
            actions.append(
                action_challenge(
                    cguild,
                    event.member,
                    reason=Message("components_worker_reason", {"reason": reason}),
                    info=info,
                    block=True,
                )
            )
        elif name == "challenge":
            actions.append(
                action_challenge(
                    cguild,
                    event.member,
                    reason=Message("components_worker_reason", {"reason": reason}),
                    info=info,
                    block=False,
                )
            )
        elif name == "log":
            actions.append(
                ILog(
                    event.guild_id,
                    Message("components_worker_log", {"message": reason}),
                    event.message_id.created_at,
                )
            )
        elif name == "announcement":
            channel = event.get_channel()
            if channel is not None:
                actions.append(
                    announcement(
                        channel,
                        Message("components_worker_announcement", {"message": reason}),
                        120,
                    )
                )
        else:
            actions.append(
                ILog(
                    event.guild_id,
                    Message(
                        "components_worker_unknownaction", {"action": action[:500]}
                    ),
                    event.message_id.created_at,
                )
            )

    return actions


listeners = [
    (hikari.GuildMessageCreateEvent, on_message_create),
]
