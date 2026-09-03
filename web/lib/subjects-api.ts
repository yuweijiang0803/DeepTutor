import { apiFetch, apiUrl } from "@/lib/api";
import { invalidateClientCache, withClientCache } from "@/lib/client-cache";

/** Subject-pack catalog row (list response, lightweight). */
export interface SubjectSummary {
  id: string;
  name: string;
  stage: string;
  grade: string;
  textbook: string;
  status: string;
  module_count: number;
  kp_count: number;
}

export interface SubjectQuestion {
  id: string;
  kp_id: string;
  question: string;
  q_type: "choice" | "fill_in_blank" | "written";
  options: string[];
  answer: string;
  explanation: string;
  difficulty: "easy" | "medium" | "hard";
  created_by: string;
  created_at: number;
  updated_at: number;
}

export interface SubjectKnowledgePoint {
  id: string;
  module_id: string;
  name: string;
  kp_type: "memory" | "procedure" | "concept" | "design";
  order_no: number;
  /** OpenMAIC 讲解课件引用（未生成时为空）。 */
  openmaic_stage_id: string;
  openmaic_url: string;
  questions: SubjectQuestion[];
  created_at: number;
  updated_at: number;
}

export interface SubjectModule {
  id: string;
  subject_id: string;
  name: string;
  order_no: number;
  pass_threshold: number;
  knowledge_points: SubjectKnowledgePoint[];
  created_at: number;
  updated_at: number;
}

export interface SubjectDetail {
  id: string;
  name: string;
  stage: string;
  grade: string;
  textbook: string;
  status: string;
  modules: SubjectModule[];
  created_at: number;
  updated_at: number;
}

async function expectJson<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response.json() as Promise<T>;
}

/** 学科包目录（轻量列表，含章/知识点计数）。 */
export async function listSubjects(options?: {
  force?: boolean;
}): Promise<SubjectSummary[]> {
  return withClientCache<SubjectSummary[]>(
    "subjects:list",
    async () => {
      const response = await apiFetch(apiUrl("/api/v1/subjects"), {
        cache: "no-store",
      });
      return (await expectJson<{ subjects: SubjectSummary[] }>(response)).subjects ?? [];
    },
    { force: options?.force, ttlMs: 15_000 },
  );
}

/** 单个学科包完整树（章→知识点→题目）。 */
export async function getSubject(
  subjectId: string,
  options?: { force?: boolean },
): Promise<SubjectDetail> {
  return withClientCache<SubjectDetail>(
    `subjects:get:${subjectId}`,
    async () => {
      const response = await apiFetch(apiUrl(`/api/v1/subjects/${subjectId}`), {
        cache: "no-store",
      });
      const payload = await expectJson<{ subject: SubjectDetail }>(response);
      if (!payload.subject) throw new Error(`Subject not found: ${subjectId}`);
      return payload.subject;
    },
    { force: options?.force, ttlMs: 15_000 },
  );
}

export function invalidateSubjects(): void {
  invalidateClientCache("subjects:");
}
