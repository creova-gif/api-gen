"""
Datapi TypeScript Client SDK Generator.
Emits a lightweight, zero-dependency TypeScript client SDK with full type definitions
matching the generated OpenAPI specification and Pydantic models.
"""

from typing import Any, Union
from datapi.infer import FieldDef
from datapi.planner import APIPlan
from datapi.python_sdk_generator import generate_python_sdk


def _ts_type_annotation(f: FieldDef) -> str:
    mapping = {
        "int": "number",
        "float": "number",
        "bool": "boolean",
        "str": "string",
        "datetime": "string",
        "date": "string",
    }
    base = mapping.get(f.python_type, "string")
    if f.enum_values:
        enum_types = " | ".join(f'"{v}"' for v in f.enum_values)
        return enum_types
    if f.nullable:
        return f"{base} | null"
    return base


def generate_typescript_sdk(plan: Union[APIPlan, Any]) -> str:
    """Generates a complete, single-file zero-dependency TypeScript client."""
    primary_schema = getattr(plan, "schema", plan)
    schemas = getattr(plan, "all_schemas", [primary_schema])
    title = getattr(plan, "title", f"{primary_schema.resource_name.capitalize()} API")
    auth_enabled = getattr(plan, "auth_enabled", False)
    res_title = primary_schema.resource_name.capitalize()
    pk = getattr(primary_schema, "primary_key", "id") or "id"

    # TypeScript Interfaces for all schemas
    interfaces_code = []
    for s in schemas:
        s_title = s.resource_name.capitalize()
        s_pk = getattr(s, "primary_key", "id") or "id"
        fields_ts = []
        create_fields_ts = []
        update_fields_ts = []

        for f in s.fields:
            ts_type = _ts_type_annotation(f)
            fields_ts.append(f"  {f.name}: {ts_type};")
            if f.name != s_pk:
                optional_marker = "?" if f.nullable else ""
                create_fields_ts.append(f"  {f.name}{optional_marker}: {ts_type};")
                update_fields_ts.append(f"  {f.name}?: {ts_type};")

        f_str = "\n".join(fields_ts)
        c_str = "\n".join(create_fields_ts) or "  [key: string]: unknown;"
        u_str = "\n".join(update_fields_ts) or "  [key: string]: unknown;"

        interfaces_code.append(f"""export interface {s_title} {{
{f_str}
}}

export interface {s_title}CreateInput {{
{c_str}
}}

export interface {s_title}UpdateInput {{
{u_str}
}}

export interface {s_title}ListResponse {{
  items: {s_title}[];
  pagination: PaginationMetadata;
}}

export interface {s_title}ListParams {{
  limit?: number;
  offset?: number;
  q?: string;
  [key: string]: unknown;
}}""")

    all_interfaces_str = "\n\n".join(interfaces_code)

    auth_header_logic = ""
    auth_param = ""
    if auth_enabled:
        auth_param = "apiKey?: string;\n  "
        auth_header_logic = """    if (this.apiKey) {
      headers["X-API-Key"] = this.apiKey;
    }
"""

    # Multi-entity methods
    multi_methods = []
    multi_accessors = []
    for s in schemas:
        s_title = s.resource_name.capitalize()
        s_plural = s.plural_name
        s_plural_title = s_plural.capitalize()

        multi_methods.append(f"""  /** List {s_plural} with pagination and filters */
  async list{s_plural_title}(params: {s_title}ListParams = {{}}): Promise<{s_title}ListResponse> {{
    const query = new URLSearchParams();
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    if (params.offset !== undefined) query.set("offset", String(params.offset));
    if (params.q !== undefined) query.set("q", params.q);

    for (const [k, v] of Object.entries(params)) {{
      if (!["limit", "offset", "q"].includes(k) && v !== undefined) {{
        query.set(k, String(v));
      }}
    }}

    const qs = query.toString();
    return this.request(`/{s_plural}${{qs ? `?${{qs}}` : ""}}`);
  }}

  /** Cursor-based pagination for {s_plural} */
  async list{s_plural_title}Cursor(params?: {{ cursor?: string; limit?: number }}): Promise<{{
    items: {s_title}[];
    nextCursor?: string;
    hasMore: boolean;
  }}> {{
    const p = (params || {{}}) as Record<string, any>;
    const limit = p.limit ?? 20;
    let offset = 0;
    if (p.cursor) {{
      try {{
        const decoded = typeof atob === "function" ? atob(p.cursor) : Buffer.from(p.cursor, "base64").toString("utf-8");
        const parsed = parseInt(decoded, 10);
        offset = isNaN(parsed) ? (parseInt(p.cursor, 10) || 0) : parsed;
      }} catch {{
        offset = parseInt(p.cursor, 10) || 0;
      }}
    }}

    const query = new URLSearchParams();
    query.set("limit", String(limit));
    query.set("offset", String(offset));
    if (p.cursor) {{
      query.set("cursor", p.cursor);
    }}

    for (const [k, v] of Object.entries(p)) {{
      if (!["cursor", "limit", "offset"].includes(k) && v !== undefined) {{
        query.set(k, String(v));
      }}
    }}

    const qs = query.toString();
    const res = await this.request<any>(`/{s_plural}${{qs ? `?${{qs}}` : ""}}`);
    const items: {s_title}[] = Array.isArray(res) ? res : (res.items || []);
    const total = res.pagination?.total;
    const nextOffset = offset + items.length;
    const hasMore = res.hasMore !== undefined
      ? Boolean(res.hasMore)
      : (total !== undefined ? nextOffset < total : items.length === limit);
    const nextCursor = res.nextCursor || (hasMore ? (typeof btoa === "function" ? btoa(String(nextOffset)) : String(nextOffset)) : undefined);

    return {{
      items,
      nextCursor,
      hasMore,
    }};
  }}

  /** Get a single {s.resource_name} by ID */
  async get{s_title}(id: string | number): Promise<{s_title}> {{
    return this.request(`/{s_plural}/${{encodeURIComponent(id)}}`);
  }}

  /** Create a new {s.resource_name} */
  async create{s_title}(payload: {s_title}CreateInput): Promise<{s_title}> {{
    return this.request(`/{s_plural}`, {{
      method: "POST",
      body: JSON.stringify(payload),
    }});
  }}

  /** Update an existing {s.resource_name} */
  async update{s_title}(id: string | number, payload: {s_title}UpdateInput): Promise<{s_title}> {{
    return this.request(`/{s_plural}/${{encodeURIComponent(id)}}`, {{
      method: "PATCH",
      body: JSON.stringify(payload),
    }});
  }}

  /** Delete a {s.resource_name} by ID */
  async delete{s_title}(id: string | number): Promise<void> {{
    return this.request(`/{s_plural}/${{encodeURIComponent(id)}}`, {{
      method: "DELETE",
    }});
  }}""")

        multi_accessors.append(f"""  get {s_plural}() {{
    return {{
      list: (params?: {s_title}ListParams) => this.list{s_plural_title}(params),
      listCursor: (params?: {{ cursor?: string; limit?: number }}) => this.list{s_plural_title}Cursor(params),
      get: (id: string | number) => this.get{s_title}(id),
      create: (payload: {s_title}CreateInput) => this.create{s_title}(payload),
      update: (id: string | number, payload: {s_title}UpdateInput) => this.update{s_title}(id, payload),
      delete: (id: string | number) => this.delete{s_title}(id),
    }};
  }}""")

    multi_methods_str = "\n\n".join(multi_methods)
    multi_accessors_str = "\n\n".join(multi_accessors)
    client_aliases = "\n".join(f"export const {s.resource_name.capitalize()}Client = {res_title}Client;" for s in schemas)

    return f"""/**
 * {title} - Typed Client SDK.
 * Auto-generated by Datapi Engine.
 * Zero external dependencies (uses native fetch and AbortSignal).
 */

export interface PaginationMetadata {{
  total: number;
  limit: number;
  offset: number;
}}

export interface CursorPage<T> {{
  items: T[];
  nextCursor?: string;
  hasMore: boolean;
}}

{all_interfaces_str}

/**
 * RFC 7807 standardized Problem Details error response.
 */
export class DatapiApiError extends Error {{
  public status: number;
  public title?: string;
  public type?: string;
  public detail?: string;
  public instance?: string;
  public data?: unknown;

  constructor(
    init:
      | number
      | {{
          status: number;
          title?: string;
          type?: string;
          detail?: string;
          instance?: string;
          data?: unknown;
          message?: string;
        }},
    messageOrData?: unknown
  ) {{
    if (typeof init === "number") {{
      const msg = typeof messageOrData === "string" ? messageOrData : `API Error [${{init}}]`;
      super(msg);
      this.status = init;
      this.detail = typeof messageOrData === "string" ? messageOrData : undefined;
      this.data = messageOrData;
    }} else {{
      super(init.message || init.detail || init.title || `API Error [${{init.status}}]`);
      this.status = init.status;
      this.title = init.title;
      this.type = init.type;
      this.detail = init.detail;
      this.instance = init.instance;
      this.data = init.data;
    }}
    this.name = "DatapiApiError";
    Object.setPrototypeOf(this, DatapiApiError.prototype);
  }}
}}

export interface ClientConfig {{
  baseUrl: string;
  {auth_param}fetch?: typeof fetch;
  maxRetries?: number;
  backoffFactor?: number;
  timeoutMs?: number;
}}

export class {res_title}Client {{
  private baseUrl: string;
  private apiKey?: string;
  private customFetch: typeof fetch;
  private maxRetries: number;
  private backoffFactor: number;
  private timeoutMs: number;

  constructor(config: ClientConfig) {{
    this.baseUrl = config.baseUrl.replace(/\\/+$/, "");
    this.apiKey = config.apiKey;
    this.customFetch = config.fetch || globalThis.fetch;
    this.maxRetries = config.maxRetries ?? 3;
    this.backoffFactor = config.backoffFactor ?? 1.5;
    this.timeoutMs = config.timeoutMs || 10000;
  }}

  private async request<T>(path: string, options: RequestInit = {{}}): Promise<T> {{
    const headers: Record<string, string> = {{
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string>),
    }};
{auth_header_logic}
    let lastError: unknown;

    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {{
      try {{
        // Request timeout handling using AbortSignal.timeout(config.timeoutMs || 10000)
        const signal = options.signal ?? AbortSignal.timeout(this.timeoutMs || 10000);
        const response = await this.customFetch(`${{this.baseUrl}}${{path}}`, {{
          ...options,
          headers,
          signal,
        }});

        // Exponential backoff retry with jitter on HTTP 429 and 503
        if ((response.status === 429 || response.status === 503) && attempt < this.maxRetries) {{
          const retryAfter = response.headers?.get?.("Retry-After");
          let delayMs: number;
          if (retryAfter && !isNaN(Number(retryAfter))) {{
            delayMs = Number(retryAfter) * 1000;
          }} else {{
            const exponential = Math.pow(this.backoffFactor, attempt) * 500;
            const jitter = Math.random() * 200;
            delayMs = exponential + jitter;
          }}
          await new Promise((resolve) => setTimeout(resolve, delayMs));
          continue;
        }}

        if (!response.ok) {{
          let errorData: any = null;
          let errorText = "";
          try {{
            const text = await response.text();
            errorText = text;
            errorData = JSON.parse(text);
          }} catch {{
            // Body is not JSON
          }}

          if (errorData && typeof errorData === "object") {{
            throw new DatapiApiError({{
              status: response.status,
              title: errorData.title,
              type: errorData.type,
              detail: errorData.detail || errorText,
              instance: errorData.instance,
              data: errorData,
            }});
          }}

          throw new DatapiApiError({{
            status: response.status,
            title: response.statusText || undefined,
            detail: errorText || `HTTP ${{response.status}}`,
            data: errorText,
          }});
        }}

        if (response.status === 204) {{
          return null as T;
        }}

        return response.json();
      }} catch (err: any) {{
        lastError = err;
        if (err instanceof DatapiApiError) {{
          throw err;
        }}
        if (options.signal?.aborted) {{
          throw err;
        }}
        if (attempt === this.maxRetries) {{
          throw err;
        }}
        const delayMs = Math.pow(this.backoffFactor, attempt) * 500 + Math.random() * 200;
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      }}
    }}

    throw lastError;
  }}

  /** Health probe check */
  async health(): Promise<{{ status: string; records_count: number }}> {{
    return this.request("/healthz");
  }}

  /** Primary entity convenience methods */
  async list(params: {res_title}ListParams = {{}}): Promise<{res_title}ListResponse> {{
    return this.list{primary_schema.plural_name.capitalize()}(params);
  }}

  async listCursor(params?: {{ cursor?: string; limit?: number }}): Promise<{{
    items: {res_title}[];
    nextCursor?: string;
    hasMore: boolean;
  }}> {{
    return this.list{primary_schema.plural_name.capitalize()}Cursor(params);
  }}

  async get(id: string | number): Promise<{res_title}> {{
    return this.get{res_title}(id);
  }}

  async create(payload: {res_title}CreateInput): Promise<{res_title}> {{
    return this.create{res_title}(payload);
  }}

  async update(id: string | number, payload: {res_title}UpdateInput): Promise<{res_title}> {{
    return this.update{res_title}(id, payload);
  }}

  async delete(id: string | number): Promise<void> {{
    return this.delete{res_title}(id);
  }}

  // Multi-entity operations
{multi_methods_str}

  // Multi-entity resource accessors
{multi_accessors_str}
}}

export const DatapiClient = {res_title}Client;
{client_aliases}
"""
