"""Navigation entries for Location Floor Plan."""

from nautobot.apps.ui import NavMenuGroup, NavMenuItem, NavMenuTab

menu_items = (
    NavMenuTab(
        name="Organization",
        groups=(
            NavMenuGroup(
                name="Locations",
                items=(
                    NavMenuItem(
                        link="plugins:location_floor_plan:floorplan_list",
                        name="Floor Plans",
                        permissions=("location_floor_plan.view_floorplan",),
                    ),
                ),
            ),
        ),
    ),
)
