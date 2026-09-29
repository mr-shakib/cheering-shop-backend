/* Signing in and out (docs/AUTH-API.md), and admin invitations (§18). */
import { useQuery } from "@tanstack/react-query";

import { ApiError, api, get, post, type AuthResult } from "@/lib/api";
import { queryClient } from "@/lib/queryClient";
import { clearSession, getSession, saveSession, updateSessionUser, type SessionUser } from "@/lib/session";

export type LoginResult = AuthResult | { requires_2fa: true; temp_token: string; expires_in: number };

export class NotAdminError extends Error {
  constructor() {
    super("That account is not an administrator. Use an admin account to sign in.");
  }
}

function adopt(result: AuthResult, remember: boolean) {
  if (result.user.role !== "ADMIN") {
    // Do not keep a non-admin's tokens around; revoke them on the way out.
    void api("POST", "/auth/logout", { body: { refresh_token: result.tokens.refresh_token } }).catch(() => {});
    throw new NotAdminError();
  }
  queryClient.clear();
  saveSession(
    { accessToken: result.tokens.access_token, refreshToken: result.tokens.refresh_token, user: result.user },
    remember,
  );
}

export async function login(email: string, password: string, remember: boolean): Promise<{ tempToken: string } | null> {
  const result = await api<LoginResult>("POST", "/auth/login", { body: { email, password }, anonymous: true });
  if ("requires_2fa" in result) return { tempToken: result.temp_token };
  adopt(result, remember);
  return null;
}

export async function login2fa(tempToken: string, code: string, remember: boolean) {
  const result = await api<AuthResult>("POST", "/auth/login/2fa", {
    body: { temp_token: tempToken, code },
    anonymous: true,
  });
  adopt(result, remember);
}

export async function signOut() {
  const session = getSession();
  clearSession();
  queryClient.clear();
  if (session) {
    // Best effort: the refresh token would otherwise stay valid for 30 days.
    await fetch("/api/v1/auth/logout", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${session.accessToken}` },
      body: JSON.stringify({ refresh_token: session.refreshToken }),
    }).catch(() => {});
  }
}

export const requestPasswordReset = (email: string) =>
  api<{ message: string }>("POST", "/auth/password/forgot", { body: { email }, anonymous: true });

export const resetPassword = (email: string, code: string, newPassword: string) =>
  api<{ message: string }>("POST", "/auth/password/reset", {
    body: { email, code, new_password: newPassword },
    anonymous: true,
  });

export function useMe(enabled: boolean) {
  return useQuery({
    queryKey: ["me"],
    enabled,
    staleTime: 5 * 60_000,
    queryFn: async ({ signal }) => {
      try {
        const me = await get<SessionUser>("/users/me", undefined, signal);
        if (me.role !== "ADMIN") {
          clearSession();
          throw new NotAdminError();
        }
        updateSessionUser(me);
        return me;
      } catch (e) {
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) clearSession();
        throw e;
      }
    },
    retry: false,
  });
}

export interface InvitationPreview {
  email: string;
  full_name: string | null;
  expires_at: string;
}

export const readInvitation = (token: string) =>
  api<InvitationPreview>("GET", `/auth/admin-invitations/${encodeURIComponent(token)}`, { anonymous: true });

export async function acceptInvitation(token: string, fullName: string, password: string) {
  const result = await api<AuthResult>("POST", "/auth/admin-invitations/accept", {
    body: { token, full_name: fullName, password },
    anonymous: true,
  });
  adopt(result, false);
}

export async function changePassword(currentPassword: string, newPassword: string) {
  const result = await post<{ message: string; tokens?: { access_token: string; refresh_token: string } }>(
    "/users/me/password",
    { current_password: currentPassword, new_password: newPassword },
  );
  const session = getSession();
  if (result.tokens && session) {
    saveSession({ ...session, accessToken: result.tokens.access_token, refreshToken: result.tokens.refresh_token });
  }
  return result;
}
