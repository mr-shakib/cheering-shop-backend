/* The console is served at /admin/ on the API host and at / on the admin
 * subdomain (ADMIN_UI_HOST rewrites onto the same files), so the router's
 * basename is whichever of the two the page was loaded under. */
export const BASENAME =
  window.location.pathname === "/admin" || window.location.pathname.startsWith("/admin/") ? "/admin" : "";
