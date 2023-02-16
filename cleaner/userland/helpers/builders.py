import typing

import hikari

# need to import these explicitly because someone forgot to add them to __all__
# fixed in dev117
from hikari.components import ChannelSelectMenuComponent, TextSelectMenuComponent


def components_to_builder(
    components: typing.Sequence[hikari.PartialComponent], rest: hikari.api.RESTClient
) -> list[hikari.api.MessageActionRowBuilder]:
    rows: list[hikari.api.MessageActionRowBuilder] = []
    for row in typing.cast(
        typing.Sequence[hikari.MessageActionRowComponent],
        components,
    ):
        rows.append(rest.build_message_action_row())
        for item in row.components:
            if isinstance(item, hikari.ButtonComponent):
                btn = rows[-1].add_button(
                    item.style,
                    typing.cast(
                        str,
                        (
                            item.url
                            if item.style == hikari.ButtonStyle.LINK
                            else item.custom_id
                        ),
                    ),
                )
                if item.label:
                    btn.set_label(item.label)
                if item.emoji:
                    btn.set_emoji(item.emoji)
                btn.set_is_disabled(item.is_disabled)
                btn.add_to_container()

            elif isinstance(item, hikari.SelectMenuComponent):
                menu = rows[-1].add_select_menu(item.type, item.custom_id)
                menu.set_min_values(item.min_values)
                menu.set_max_values(item.max_values)
                menu.set_is_disabled(item.is_disabled)
                if isinstance(item, TextSelectMenuComponent):
                    assert isinstance(menu, TextSelectMenuComponent)
                    menu.options = item.options
                elif isinstance(item, ChannelSelectMenuComponent):
                    assert isinstance(menu, ChannelSelectMenuComponent)
                    menu.channel_types = item.channel_types

                menu.add_to_container()

    return rows
