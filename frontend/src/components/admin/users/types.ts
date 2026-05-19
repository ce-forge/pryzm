export interface AdminUser {
  id: string;
  username: string;
  email: string | null;
  is_admin: boolean;
  is_active: boolean;
  can_create_workspaces: boolean;
  allowed_tools: string[];
  created_at: string | null;
  last_login_at: string | null;
}

export interface WorkspaceTemplate {
  id: string;
  slug: string;
  display_name: string;
}

export interface StarterTemplateSelection {
  template_id: string;
  owner_can_edit: boolean;
}

export const PASSWORD_MIN = 4;
