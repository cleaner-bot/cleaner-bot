import time
import typing
from functools import lru_cache

import filterrules
import hikari
import msgpack  # type: ignore
import rust_regex

from ._types import ConfigType, FilterRuleTriggeredEvent, KernelType
from .helpers.binding import complain_if_none, safe_call
from .helpers.localization import Message


class ConfigurationRule(typing.NamedTuple):
    action: str
    name: str
    code: bytes


@lru_cache
def regex_compile(pattern: str) -> typing.Any:
    return rust_regex.compile(pattern)  # type: ignore


functions: dict[str, typing.Callable[..., bytes | int | bool]] = {
    "regex_match": lambda a, b: bool(
        regex_compile(a.decode()).findall(b.decode())  # type: ignore
    ),
    "len": len,
    "lower": bytes.lower,
    "upper": bytes.upper,
    "starts_with": bytes.startswith,
    "contains": lambda a, b: b in a,
    "ends_with": bytes.endswith,
    "to_string": lambda a: str(a).encode(),
}
actions = {
    "challenge": 0,
    "auto": 1,
    "kickonly": 2,
    "banonly": 3,
}


def var_user(user: hikari.User) -> dict[str, bytes | int | bool]:
    return {
        "user.id": int(user.id),
        "user.username": user.username.encode(),
        "user.discriminator": user.discriminator.encode(),
        "user.created_at": int(user.id.created_at.timestamp()),
        "user.has_avatar": user.avatar_hash is not None,
        "user.avatar_hash": user.avatar_hash.encode() if user.avatar_hash else b"",
        "user.flags": user.flags,
    }


def var_member(member: hikari.Member) -> dict[str, bytes | int | bool]:
    return {
        "member.nickname": member.nickname.encode() if member.nickname else b"",
        "member.joined_at": int(member.joined_at.timestamp()),
    }


def var_message(message: hikari.PartialMessage) -> dict[str, bytes | int | bool]:
    return {
        "message.content": message.content.encode() if message.content else b"",
        "message.has_embeds": bool(message.embeds),
        "message.has_attachments": bool(message.attachments),
        "message.type": message.type if message.type is not hikari.UNDEFINED else -1,
        "message.flags": message.flags if message.flags is not hikari.UNDEFINED else -1,
    }


class FilterRulesService:
    def __init__(self, kernel: KernelType) -> None:
        self.kernel = kernel

        self.kernel.bindings["filterrule:member"] = self.member_phase
        self.kernel.bindings["filterrule:message"] = self.message_phase

    async def get_rules(self, guild_id: int, name: str) -> list[ConfigurationRule]:
        raw_rules = await self.kernel.database.lrange(
            f"guild:{guild_id}:filterrules:{name}", 0, -1
        )
        return [
            ConfigurationRule(*msgpack.unpackb(x, use_list=False)) for x in raw_rules
        ]

    async def member_phase(
        self, member: hikari.Member, config: ConfigType, phase: str
    ) -> bool:
        rules = await self.get_rules(member.guild_id, phase)
        if not rules:
            return False
        elif all(rule.action in ("disabled", "skip") for rule in rules):
            return False

        vars: dict[str, bytes | int | bool] = {
            **var_user(member),
            **var_member(member),
            "guild.id": int(member.guild_id),
        }

        matched_rule = self.run_rules(phase, rules, vars)
        if matched_rule is None or matched_rule.action in ("disabled", "skip"):
            return False
        elif matched_rule.action not in actions:
            return False  # invalid action

        if challenge := complain_if_none(
            self.kernel.bindings.get("http:challenge"), "http:challenge"
        ):
            if track := complain_if_none(self.kernel.bindings.get("track"), "track"):
                info: FilterRuleTriggeredEvent = {
                    "name": "filterrule",
                    "guild_id": member.guild_id,
                    "phase": phase,
                    "action": matched_rule.action,
                }
                await safe_call(track(info), True)

            reason = Message(
                "log_filterrule",
                {
                    "phase": phase,
                    "name": matched_rule.name,
                    "action": matched_rule.action,
                },
            )
            await safe_call(
                challenge(
                    member, config, False, reason, actions.get(matched_rule.action, 1)
                ),
                True,
            )

        return True

    async def message_phase(
        self, message: hikari.PartialMessage, config: ConfigType, phase: str
    ) -> bool:
        assert message.member
        assert message.guild_id
        rules = await self.get_rules(message.guild_id, phase)
        if not rules:
            return False
        elif all(rule.action in ("disabled", "skip") for rule in rules):
            return False

        vars: dict[str, bytes | int | bool] = {
            **var_user(message.member),
            **var_member(message.member),
            **var_message(message),
            "guild.id": int(message.guild_id),
        }

        matched_rule = self.run_rules(phase, rules, vars)
        if matched_rule is None or matched_rule.action in ("disabled", "skip"):
            return False

        reason = Message(
            "log_filterrule",
            {
                "phase": phase,
                "name": matched_rule.name,
                "action": matched_rule.action,
            },
        )
        if delete := complain_if_none(
            self.kernel.bindings.get("http:delete"), "http:delete"
        ):
            await safe_call(
                delete(
                    message.id,
                    message.channel_id,
                    message.member.user,
                    True,
                    reason,
                    message,
                ),
                True,
            )

        if (
            announcement := complain_if_none(
                self.kernel.bindings.get("http:announcement"),
                "http:announcement",
            )
        ) and matched_rule.action in ("delete", "challenge"):
            announcement_message = Message(
                "components_filterrules",
                {"user": message.member.id},
            )

            await safe_call(
                announcement(
                    message.guild_id, message.channel_id, announcement_message, 20
                ),
                True,
            )

        if challenge := complain_if_none(
            self.kernel.bindings.get("http:challenge"), "http:challenge"
        ):
            if track := complain_if_none(self.kernel.bindings.get("track"), "track"):
                info: FilterRuleTriggeredEvent = {
                    "name": "filterrule",
                    "guild_id": message.guild_id,
                    "phase": phase,
                    "action": matched_rule.action,
                }
                await safe_call(track(info), True)

            await safe_call(
                challenge(
                    message.member,
                    config,
                    matched_rule.action == "delete",
                    reason,
                    actions.get(matched_rule.action, 0),
                ),
                True,
            )

        return True

    def run_rules(
        self,
        phase: str,
        rules: list[ConfigurationRule],
        vars: dict[str, bytes | int | bool],
    ) -> ConfigurationRule | None:
        vars.update(
            {
                "current.time": int(time.time()),
                "current.phase": phase.encode(),
                "true": True,
                "false": False,
            }
        )
        for rule in rules:
            if rule.action == "skip":
                continue
            fn = self.get_rule(rule.code)
            if fn(vars, functions):
                return rule

        return None

    @lru_cache
    def get_rule(
        self, code: bytes
    ) -> typing.Callable[
        [dict[str, typing.Any], dict[str, typing.Callable[..., typing.Any]]], typing.Any
    ]:
        ast = filterrules.parse(code)
        return filterrules.Rule(ast).compile()
