import sqlite3
import pandas as pd
from rich.console import Console
from rich.table import Table

def view_db():
    console = Console()
    
    try:
        conn = sqlite3.connect("anton_rx.db")
    except sqlite3.OperationalError:
        console.print("[red]Database not found (anton_rx.db)[/red]")
        return
        
    cursor = conn.cursor()
    
    # 1. Show Documents
    cursor.execute("SELECT * FROM documents")
    docs = cursor.fetchall()
    if docs:
        doc_table = Table(title="Documents Table", show_lines=True)
        doc_table.add_column("doc_id", style="cyan")
        doc_table.add_column("filename")
        doc_table.add_column("hash")
        doc_table.add_column("parsed_at")
        
        for doc in docs:
            doc_table.add_row(str(doc[0]), doc[1], str(doc[2])[:10] + "...", doc[3])
        console.print(doc_table)
    else:
        console.print("[yellow]No documents found in DB.[/yellow]")
        
    print("\n")
    
    # 2. Show Extracts (The Drugs)
    cursor.execute("""
        SELECT brand_name, drug_category, coverage_status, prior_auth_required, 
               prior_auth_criteria, _confidence
        FROM drug_policies
    """)
    extracts = cursor.fetchall()
    
    if extracts:
        ex_table = Table(title=f"Extracted Drugs ({len(extracts)} rows)", show_lines=True)
        ex_table.add_column("Drug Name", style="cyan")
        ex_table.add_column("Category")
        ex_table.add_column("Coverage")
        ex_table.add_column("PA Req")
        ex_table.add_column("PA Criteria")
        ex_table.add_column("Confidence")
        
        # Limit to first 25 for display brevity
        for ex in extracts[:25]:
            # truncate criteria string for display
            criteria = (ex[4][:40] + "...") if ex[4] and len(ex[4]) > 40 else ex[4]
            # color confidence
            conf_color = "green" if ex[5] == "HIGH" else "yellow"
            
            ex_table.add_row(
                ex[0],
                ex[1] or "",
                ex[2] or "",
                ex[3] or "",
                criteria or "",
                f"[{conf_color}]{ex[5]}[/{conf_color}]" if ex[5] else ""
            )
            
        console.print(ex_table)
        if len(extracts) > 25:
            console.print(f"[dim]... and {len(extracts) - 25} more rows. Run full query to see all.[/dim]")
    else:
        console.print("[yellow]No active_extracts found.[/yellow]")

    conn.close()

if __name__ == "__main__":
    view_db()
