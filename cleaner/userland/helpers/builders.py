import typing

import hikari

# need to import these explicitly because someone forgot to add them to __all__
# fixed in dev117
from hikari.components import (
    ChannelSelectMenuComponent,
    InteractiveButtonTypesT,
    TextSelectMenuComponent,
)


def components_to_builder(
    components: typing.Sequence[hikari.PartialComponent], rest: hikari.api.RESTClient
) -> list[hikari.api.MessageActionRowBuilder]:
    kwargs: dict[str, typing.Any]
    rows: list[hikari.api.MessageActionRowBuilder] = []
    for row in typing.cast(
        typing.Sequence[hikari.MessageActionRowComponent],
        components,
    ):
        rows.append(rest.build_message_action_row())
        for item in row.components:
            if isinstance(item, hikari.ButtonComponent):
                kwargs = {}
                if item.emoji:
                    kwargs["emoji"] = item.emoji
                if item.label:
                    kwargs["label"] = item.label
                kwargs["is_disabled"] = item.is_disabled

                if item.style == hikari.ButtonStyle.LINK:
                    assert item.url
                    rows[-1].add_link_button(item.url, **kwargs)
                else:
                    assert item.style and item.custom_id
                    rows[-1].add_interactive_button(
                        typing.cast(InteractiveButtonTypesT, item.style),
                        item.custom_id,
                        **kwargs
                    )

            elif isinstance(item, hikari.SelectMenuComponent):
                kwargs = {
                    "min_values": item.min_values,
                    "max_values": item.max_values,
                    "is_disabled": item.is_disabled,
                }
                if item.placeholder:
                    kwargs["placeholder"] = item.placeholder

                if isinstance(item, TextSelectMenuComponent):
                    menu = rows[-1].add_text_menu(item.custom_id, **kwargs)
                    menu.options = item.options  # type: ignore
                elif isinstance(item, ChannelSelectMenuComponent):
                    if item.channel_types:
                        kwargs["channel_types"] = item.channel_types
                    rows[-1].add_channel_menu(item.custom_id, **kwargs)
                else:
                    rows[-1].add_select_menu(item.type, item.custom_id, **kwargs)

    return rows
