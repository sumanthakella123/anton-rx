import { google } from "@ai-sdk/google";
import { frontendTools } from "@assistant-ui/react-ai-sdk";
import {
  streamText,
  convertToModelMessages,
  stepCountIs,
  type UIMessage,
  JSONSchema7,
  tool,
} from "ai";
import { z } from "zod";
import Database from "better-sqlite3";
import path from "path";

// Tell Next.js this route is always dynamic so it is never statically
// pre-rendered during `next build` (which would try to open the DB at
// build time when the file doesn't exist yet).
export const dynamic = "force-dynamic";

// Lazy singleton — the DB connection is created on the first real request,
// not at module-evaluation time (which happens during `next build`).
let _db: InstanceType<typeof Database> | null = null;
function getDb(): InstanceType<typeof Database> {
  if (!_db) {
    // DB_PATH env var is used in deployed environments (set to 'data/anton_rx.db').
    // Falls back to the sibling-folder path for local development.
    // turbopackIgnore prevents Turbopack from tracing the entire filesystem on
    // these dynamic path.join calls during the production build.
    const dbPath = process.env.DB_PATH
      ? path.join(/*turbopackIgnore: true*/ process.cwd(), process.env.DB_PATH)
      : path.join(/*turbopackIgnore: true*/ process.cwd(), '../anton-rx-backend/anton_rx.db');
    _db = new Database(dbPath, { readonly: true });
  }
  return _db;
}

const SYSTEM_PROMPT = `You are the Anton Rx Medical Policy Assistant.
You are a specialized AI designed to help users quickly look up and understand medical benefit drug policies across payers.

CRITICAL TOOL USAGE RULES — READ CAREFULLY:
1. The 'query' parameter in ALL tools must be the DRUG NAME ONLY. NEVER include a payer name, health plan name, or any other text in the 'query' field.
   - CORRECT:   query="Botox",  payer="UnitedHealthcare"
   - INCORRECT: query="Botox UnitedHealthcare"
   - CORRECT:   query="Humira"
   - INCORRECT: query="Humira covered by Cigna"
2. If the user asks about a specific payer (e.g., "Does UnitedHealthcare cover Botox?"), use 'search_drug_policy' with the drug name in 'query' AND the payer name in the optional 'payer' field.
3. When asked to compare a drug across "all" payers or "multiple" payers and you do not know the exact payer names, first use 'get_available_payers'.
4. The 'compare_drug_between_payers' tool's 'health_plans' parameter is OPTIONAL. Omit it to search all payers.
5. If asked about recently updated policies or policy changes, use 'get_policy_changes'.
6. When using 'compare_drug_between_payers', do NOT restate the raw data in your response — the UI renders an interactive table automatically. Provide only a 1-2 sentence executive summary of the key difference.
7. For single-drug lookups, provide a clear summary: coverage status, whether prior auth is required, and the key criteria.`;

export async function POST(req: Request) {
  const {
    messages,
    system,
    tools,
  }: {
    messages: UIMessage[];
    system?: string;
    tools?: Record<string, { description?: string; parameters: JSONSchema7 }>;
  } = await req.json();

  // @ts-ignore
  const result = streamText({
    model: google("gemini-2.5-flash"),
    messages: await convertToModelMessages(messages),
    system: system || SYSTEM_PROMPT,
    stopWhen: stepCountIs(5),
    tools: {
      ...frontendTools(tools ?? {}),
      // @ts-ignore
      search_drug_policy: tool({
        description: "Searches the Anton Rx database for drug policies, coverage, and prior authorization criteria. The 'query' field must contain ONLY the drug name — never include a payer name in it.",
        parameters: z.object({
          query: z.string().describe("The drug name ONLY (brand or generic). Examples: 'Botox', 'Humira', 'bevacizumab'. Do NOT include payer names here."),
          payer: z.string().optional().describe("OPTIONAL: Filter results to a specific health plan (e.g., 'UnitedHealthcare', 'Cigna', 'Florida Blue'). Use this when the user asks about a specific payer."),
        }),
        // @ts-expect-error - AI SDK model generic resolution mismatch
        execute: async (args: any) => {
          try {
            const drugName = args?.query || args?.drug_name;
            if (!drugName) {
              return { success: false, message: "Error: You must provide a drug name to search." };
            }
            const like = `%${drugName}%`;
            const payerFilter = args?.payer?.trim();

            let sql = `
              SELECT d.payer, d.effective_date, dp.brand_name, dp.generic_name, dp.drug_category,
                     dp.coverage_status, dp.prior_auth_required, dp.prior_auth_criteria, dp.step_therapy_required,
                     dp.biosimilar_step_detail, dp.hcpcs_codes, dp.maximum_units, dp.authorization_duration,
                     dp.indications, dp.icd10_codes
              FROM drug_policies dp
              JOIN documents d ON dp.document_id = d.id
              WHERE (dp.brand_name LIKE ? OR dp.generic_name LIKE ?)
            `;
            const params: any[] = [like, like];

            if (payerFilter) {
              sql += ` AND d.payer LIKE ?`;
              params.push(`%${payerFilter}%`);
            }

            sql += ` LIMIT 15`;

            const rows = getDb().prepare(sql).all(...params);

            if (rows.length === 0) {
              const context = payerFilter ? ` under ${payerFilter}` : "";
              return { success: false, message: `No policy found for '${drugName}'${context}. Try a different spelling or payer name.` };
            }

            return { success: true, policies: rows as any[] };
          } catch (error) {
            console.error("Database query failed:", error);
            return { success: false, message: "A database error occurred while searching for the drug policy." };
          }
        },
      }),
      // @ts-ignore
      compare_drug_between_payers: tool({
        description: "Compares the coverage and prior authorization criteria for a specific drug across multiple payers simultaneously. Returns a matrix array of policies.",
        parameters: z.object({
          query: z.string().describe("The REQUIRED exact name of the drug to look up (e.g., 'Avastin', 'Humira')."),
          health_plans: z.string().optional().describe("OPTIONAL: A comma-separated list of health plan names (e.g., 'UnitedHealthcare Commercial, Blue Cross NC'). If omitted, searching all available payers.")
        }),
        // @ts-expect-error - AI SDK model generic resolution mismatch
        execute: async (args: any) => {
          console.log("TOOL CALL compare_drugs ARGS:", args);
          try {
             const drugName = args?.query || args?.drug_name;
             if (!drugName) {
                 return { success: false, message: "Error: Must provide the drug query." };
             }
             
             const payersArg = args?.health_plans || args?.payers;
             let payerList: string[] = [];
             if (payersArg) {
                 if (Array.isArray(payersArg)) {
                     payerList = payersArg.map((p: any) => String(p).trim());
                 } else if (typeof payersArg === "string") {
                     payerList = payersArg.split(',').map((p: string) => p.trim());
                 }
             }
             
             const like = `%${drugName}%`;
             let rows;
             if (payerList.length > 0) {
                 const payerPlaceholders = payerList.map(() => '?').join(',');
                 const sql = `
                  SELECT d.payer, d.effective_date, dp.brand_name, dp.generic_name,
                         dp.coverage_status, dp.prior_auth_required, dp.step_therapy_required, dp.prior_auth_criteria
                  FROM drug_policies dp
                  JOIN documents d ON dp.document_id = d.id
                  WHERE (dp.brand_name LIKE ? OR dp.generic_name LIKE ?) AND d.payer IN (${payerPlaceholders})
                  GROUP BY d.payer
                 `;
                 const stmt = getDb().prepare(sql);
                 rows = stmt.all(like, like, ...payerList);
             } else {
                 const sql = `
                  SELECT d.payer, d.effective_date, dp.brand_name, dp.generic_name,
                         dp.coverage_status, dp.prior_auth_required, dp.step_therapy_required, dp.prior_auth_criteria
                  FROM drug_policies dp
                  JOIN documents d ON dp.document_id = d.id
                  WHERE (dp.brand_name LIKE ? OR dp.generic_name LIKE ?)
                  GROUP BY d.payer
                  LIMIT 15
                 `;
                 const stmt = getDb().prepare(sql);
                 rows = stmt.all(like, like);
             }
             
             return { success: true, comparison: rows as any[] };
          } catch (error) {
             console.error("Comparison query failed:", error);
             return { success: false, message: "A database error occurred during comparison." };
          }
        }
      }),
      // @ts-ignore
      get_available_payers: tool({
          description: "Returns a unique list of all health plan names (payers) currently indexed in the Anton Rx system.",
          parameters: z.object({}),
          // @ts-expect-error - AI SDK model generic resolution mismatch
          execute: async () => {
              try {
                  const stmt = getDb().prepare("SELECT DISTINCT payer FROM documents ORDER BY payer ASC");
                  const payers = stmt.all();
                  return { success: true, payers: payers.map((p: any) => p.payer) };
              } catch (error) {
                  console.error("Failed to fetch payers:", error);
                  return { success: false, message: "A database error occurred while fetching payers." };
              }
          }
      }),
      // @ts-ignore
      get_policy_changes: tool({
        description: "Retrieves recent policy updates, change logs, and review summaries from health plans. Use this to answer questions about what changed in a policy, recent updates, or historical shifts in coverage.",
        parameters: z.object({
          payer: z.string().optional().describe("OPTIONAL: The health plan/payer name (e.g. 'UnitedHealthcare', 'Cigna')."),
          keyword: z.string().optional().describe("OPTIONAL: A topic or drug class to filter policies by (e.g. 'oncology', 'multiple sclerosis', 'Herceptin')."),
        }),
        // @ts-expect-error - AI SDK model generic resolution mismatch
        execute: async (args: any) => {
          try {
            let sql = `SELECT payer, policy_title, effective_date, policy_review_cycle, policy_change_log FROM documents WHERE 1=1`;
            const params: any[] = [];
            
            if (args?.payer) {
              sql += ` AND payer LIKE ?`;
              params.push(`%${args.payer}%`);
            }
            if (args?.keyword) {
              sql += ` AND (policy_title LIKE ? OR policy_change_log LIKE ? OR raw_text LIKE ?)`;
              params.push(`%${args.keyword}%`, `%${args.keyword}%`, `%${args.keyword}%`);
            }
            
            sql += ` ORDER BY effective_date DESC LIMIT 20`;
            const stmt = getDb().prepare(sql);
            const rows = stmt.all(...params);
            
            if (rows.length === 0) {
              return { success: false, message: "No policy changes found matching the criteria." };
            }
            return { success: true, changes: rows as any[] };
          } catch (error) {
            console.error("Policy changes query failed:", error);
            return { success: false, message: "A database error occurred." };
          }
        }
      }),
    },
  });

  return result.toUIMessageStreamResponse();
}
