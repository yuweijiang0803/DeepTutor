"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getActiveRole,
  setActiveRole,
  roleLabel,
  type OrgRole,
} from "@/lib/roles-api";

/**
 * Organisational identity switcher (XiaoZhi school/clase/role).
 *
 * Renders a small "switch role" button; clicking opens a modal listing every
 * identity the user holds. Choosing one persists it as the active identity,
 * which decides the class's shared knowledge base / learning data scope.
 *
 * Hidden entirely when the user has only one identity.
 */
export function RoleSwitcher() {
  const { t } = useTranslation();
  const [roles, setRoles] = useState<OrgRole[]>([]);
  const [active, setActive] = useState<OrgRole | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    getActiveRole().then((res) => {
      setRoles(res.roles);
      setActive(res.active_role);
    });
  }, []);

  // Only meaningful when the user holds a teacher/principal identity — a
  // pure-student account has nothing to switch between (every identity is the
  // student view).
  const hasNonStudentRole = roles.some((r) =>
    ["clase", "school", "admin"].includes(r.role),
  );
  if (roles.length <= 1 || !hasNonStudentRole) return null;

  async function handleSelect(role: OrgRole) {
    const updated = await setActiveRole(role);
    if (updated) {
      setActive(updated);
      setOpen(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex shrink-0 items-center gap-1 rounded-full border border-[var(--border)] px-2.5 py-1 text-[11.5px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
      >
        {t("Switch role")}
      </button>

      {open && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4"
          onClick={() => setOpen(false)}
        >
          <div
            className="w-full max-w-sm rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-[15px] font-semibold text-[var(--foreground)]">
                {t("Switch identity")}
              </h3>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="text-lg leading-none text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                aria-label={t("Close")}
              >
                ×
              </button>
            </div>

            <div className="max-h-[50vh] space-y-1 overflow-y-auto">
              {roles.map((role) => {
                const isActive =
                  active?.school_id === role.school_id &&
                  active?.clase_id === role.clase_id &&
                  active?.role === role.role;
                return (
                  <button
                    key={`${role.school_id}:${role.clase_id}:${role.role}`}
                    type="button"
                    onClick={() => handleSelect(role)}
                    className={`flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-left text-[13px] transition-colors ${
                      isActive
                        ? "bg-[var(--primary)]/10 text-[var(--primary)]"
                        : "text-[var(--foreground)] hover:bg-[var(--background)]/50"
                    }`}
                  >
                    <span className="truncate">{roleLabel(role)}</span>
                    {isActive && <span className="text-[12px]">✓</span>}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
