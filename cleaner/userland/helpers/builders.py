import typing

import hikari


def components_to_builder(
    components: typing.Sequence[hikari.PartialComponent], rest: hikari.api.RESTClient
) -> list[hikari.api.ActionRowBuilder]:
    rows: list[hikari.api.ActionRowBuilder] = []
    for row in typing.cast(
        typing.Sequence[hikari.ActionRowComponent],
        components,
    ):
        rows.append(rest.build_action_row())
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
                menu = rows[-1].add_select_menu(item.custom_id)
                menu.set_min_values(item.min_values)
                menu.set_max_values(item.max_values)
                menu.set_is_disabled(item.is_disabled)
                for option in item.options:
                    opt = menu.add_option(option.label, option.value)
                    if option.description:
                        opt.set_description(option.description)
                    if option.emoji:
                        opt.set_emoji(option.emoji)
                    opt.set_is_default(option.is_default)
                menu.add_to_container()

    return rows
