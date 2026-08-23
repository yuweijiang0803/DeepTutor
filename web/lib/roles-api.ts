import { apiFetch, apiUrl } from "@/lib/api";

export interface OrgRole {
  school_id: string;
  school_name: string;
  clase_id: string;
  clase_name: string;
  role: string;
}

export interface ActiveRoleResponse {
  active_role: OrgRole | null;
  roles: OrgRole[];
}

/** List every organisational identity the user holds (XiaoZhi school/clase/role). */
export async function listRoles(): Promise<OrgRole[]> {
  const res = await apiFetch(apiUrl("/api/v1/roles"));
  if (!res.ok) return [];
  const data = (await res.json()) as { roles?: OrgRole[] };
  return Array.isArray(data.roles) ? data.roles : [];
}

/** Fetch the active identity, falling back to the first role server-side. */
export async function getActiveRole(): Promise<ActiveRoleResponse> {
  const res = await apiFetch(apiUrl("/api/v1/roles/active"));
  if (!res.ok) return { active_role: null, roles: [] };
  const data = (await res.json()) as ActiveRoleResponse;
  return {
    active_role: data.active_role ?? null,
    roles: Array.isArray(data.roles) ? data.roles : [],
  };
}

/** Switch the user's active identity (must be one of their roles). */
export async function setActiveRole(
  role: OrgRole,
): Promise<OrgRole | null> {
  const res = await apiFetch(apiUrl("/api/v1/roles/active"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      school_id: role.school_id,
      clase_id: role.clase_id,
      role: role.role,
    }),
  });
  if (!res.ok) return null;
  const data = (await res.json()) as { active_role?: OrgRole };
  return data.active_role ?? null;
}

const ROLE_LABELS: Record<string, string> = {
  // XiaoZhi roles table semantics: school/admin = 校长, clase = 老师, student = 学生
  school: "校长",
  admin: "校长",
  clase: "老师",
  student: "学生",
  teacher: "老师",
  parent: "家长",
};

export function roleLabel(role: OrgRole | null | undefined): string {
  if (!role) return "";
  const roleName = ROLE_LABELS[role.role] ?? role.role;
  // 老师/学生挂在班级上：显示"班级 · 身份"；校长等学校级：显示"学校 · 身份"
  if (role.clase_name) return `${role.clase_name} · ${roleName}`;
  if (role.school_name) return `${role.school_name} · ${roleName}`;
  return roleName;
}
