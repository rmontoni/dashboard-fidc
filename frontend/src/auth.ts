import { API_BASE } from './types'

export const STORAGE_TOKEN = 'fidc_auth_token'

export type PerfilUsuario = 'admin' | 'usuario'

export type UsuarioSessao = {
  id: number
  nome: string
  username: string
  perfil: PerfilUsuario
}

export function getToken(): string | null {
  return localStorage.getItem(STORAGE_TOKEN)
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(STORAGE_TOKEN, token)
  else localStorage.removeItem(STORAGE_TOKEN)
}

export function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = getToken()
  return {
    ...(extra ?? {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

export async function fetchAuth(input: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers ?? {})
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  return fetch(input, { ...init, headers })
}

export async function login(username: string, senha: string): Promise<UsuarioSessao> {
  const res = await fetch(`${API_BASE}/fidc/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, senha }),
  })
  const json = await res.json()
  if (!res.ok) {
    throw new Error(typeof json.detail === 'string' ? json.detail : 'Falha no login.')
  }
  setToken(String(json.token))
  return json.usuario as UsuarioSessao
}

export async function carregarSessao(): Promise<UsuarioSessao | null> {
  const token = getToken()
  if (!token) return null
  try {
    const res = await fetchAuth(`${API_BASE}/fidc/auth/me`)
    if (!res.ok) {
      setToken(null)
      return null
    }
    const json = await res.json()
    return json.usuario as UsuarioSessao
  } catch {
    return null
  }
}

export function logout() {
  setToken(null)
}
