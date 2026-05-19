export interface AdminWorkspace {
  id: string;
  slug: string;
  display_name: string;
  user_id: string | null;
  template_id: string | null;
  owner_can_edit: boolean;
  owner_username: string | null;
  template_display_name: string | null;
  color: string | null;
  created_at: string | null;
}

export interface AdminTemplate {
  id: string;
  slug: string;
  display_name: string;
  system_prompt?: string;
  enabled_tools?: string[];
  engine_config?: Record<string, unknown>;
  color: string | null;
}

export interface AdminUserRow {
  id: string;
  username: string;
}
