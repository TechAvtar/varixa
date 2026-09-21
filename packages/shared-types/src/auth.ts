/** Mirrors `app/schemas/auth.py`. */

export interface RegisterRequest {
  email: string;
  password: string;
  name?: string | null;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RefreshRequest {
  refresh_token: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  /** Access-token lifetime in seconds. */
  expires_in: number;
}

export type UserRole = "user" | "admin";

export interface UserResponse {
  id: string;
  email: string;
  name: string | null;
  role: UserRole;
  created_at: string;
}
