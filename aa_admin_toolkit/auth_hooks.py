from allianceauth.services.hooks import MenuItemHook, UrlHook
from allianceauth import hooks
from .actions import user_can_view
from . import urls

class AdminToolkitMenuItem(MenuItemHook):
    """ This class ensures only authorized users see the menu item """
    def __init__(self):
        MenuItemHook.__init__(
            self,
            "Admin Toolkit",
            "fas fa-tools fa-fw",
            "aa_admin_toolkit:dashboard",
            navactive=["aa_admin_toolkit:"]
        )

    def render(self, request):
        if user_can_view(request.user):
            return MenuItemHook.render(self, request)
        return ""

@hooks.register("menu_item_hook")
def register_menu():
    return AdminToolkitMenuItem()

@hooks.register("url_hook")
def register_urls():
    return UrlHook(urls, "aa_admin_toolkit", "^admin-toolkit/")
