import hikari


def add_link(component: hikari.api.ActionRowBuilder, label: str, url: str):
    (
        component.add_button(hikari.ButtonStyle.LINK, url)
        .set_label(label)
        .add_to_container()
    )
