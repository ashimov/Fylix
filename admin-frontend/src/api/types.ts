export interface AdminPublic {
  id: string;
  email: string;
  role: string;
  disabled: boolean;
  totp_enrolled: boolean;
  last_login_at: string | null;
}

export interface LoginRequest {
  email: string;
  password: string;
  totp_code: string;
}

export interface LoginResponse {
  admin: AdminPublic;
}
