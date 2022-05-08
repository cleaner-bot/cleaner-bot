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
local setmetatable = setmetatable
local script, cycle_limit
local function safe_call(fn, ...)
    if cycle_limit == nil then
        error("no cycle limit, call set_cycle_limit")
    end
    debug_sethook(coroutine.yield, cycle_limit)
    local coro = coroutine.create(fn)
    local ok, result = coroutine.resume(coro, ...)
    debug_sethook()
    if coroutine.status(coro) == "suspended" then
        error("reached cycle limit")
    end
    setmetatable(result, {})
    return result
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
    boot = lua.eval(LUA_BOOT)
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
    member = event.member
    if (
        member is None
        or data is None
        or not data.config.workers_enabled
        or not data.entitlements.workers
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

    lua, boot = worker[1]

    guild = event.get_guild()
    if guild is None:
        return

    permissions = 0
    for role in member.get_roles():
        permissions |= role.permissions

    event = lua.table_from(
        {
            "message_id": event.message_id,
            "channel_id": event.channel_id,
            "guild_id": event.guild_id,
            "member_id": event.author_id,
            "member_roles": member.role_ids,
            "member_is_bot": event.is_bot,
            "member_permissions": permissions,
            "member_is_owner": event.author_id == guild.owner_id,
            "member_is_moderator": is_moderator(cguild, member),
            "content": event.content,
            "attachments": lua.table_from(
                [
                    lua.table_from(
                        {
                            "attachment_id": a.id,
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
                            "footer_icon": e.footer
                            and e.footer.icon
                            and e.footer.icon.url,
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
                            "author_icon_url": e.author
                            and e.author.icon
                            and e.author.icon.url,
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
            "application_id": event.message.application_id,
            "mention_everyone": event.message.mentions.everyone,
            "mention_users": event.message.mentions.user_ids,
            "mention_roles": event.message.mentions.role_ids,
            "mention_channels": event.message.mentions.channels_ids,
            "interaction": event.message.interaction
            and lua.table_from(
                {
                    "id": event.message.interaction.id,
                    "type": int(event.message.interaction.type),
                    "name": event.message.interaction.name,
                    "user_id": event.message.interaction.user.id,
                }
            ),
        }
    )

    try:
        result = boot.call(event)
    except lupa.LuaError as e:
        if not data.config.logging_enabled:
            return
        return [
            ILog(
                event.guild_id,
                Message("components_worker_error", {"error": e.args[0]}),
                event.message_id.created_at,
            )
        ]

    actions: list[IGuildEvent] = []
    info = {"rule": "worker", "guild": event.guild_id}
    for i in range(len(result)):
        action = result[i]
        if action == "delete":
            actions.append(
                action_delete(
                    member,
                    event.message,
                    reason=Message("components_worker_reason"),
                    info=info,
                )
            )
        elif action == "block":
            actions.append(
                action_challenge(
                    cguild,
                    member,
                    reason=Message("components_worker_reason"),
                    info=info,
                    block=True,
                )
            )
        elif action == "challenge":
            actions.append(
                action_challenge(
                    cguild,
                    member,
                    reason=Message("components_worker_reason"),
                    info=info,
                    block=False,
                )
            )
        elif action.startswith("log:"):
            message = action[4:500]
            actions.append(
                ILog(
                    event.guild_id,
                    Message("components_worker_log", {"message": message}),
                    event.message_id.created_at,
                )
            )
        elif action.startswith("announcement:"):
            message = action[13:500]
            channel = event.get_channel()
            if channel is not None:
                actions.append(
                    announcement(
                        channel,
                        Message("components_worker_announcement", {"message": message}),
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
    (hikari.MessageCreateEvent, on_message_create),
]
