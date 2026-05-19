"""
Project-wide contracts for the paper crawler agent.

Keep user-facing data contracts here so crawlers, storage, prompts, and tests
do not each invent their own version of the schema.
"""

PUBLIC_PAPER_FIELDS = ("venue", "year", "title", "authors", "pdf_url", "source_url")
PUBLIC_PAPER_FIELDS_TEXT = ", ".join(PUBLIC_PAPER_FIELDS)

# Internal-only field used while enriching papers from detail pages.
INTERNAL_DETAIL_URL_FIELD = "detail_url"

RELEASED_STATUSES = {
    "released_fixed_parser",
    "released_saved_rule",
    "released_saved_script",
    "released_generated_rule",
    "released_generated_script",
}

RELEASE_JUDGE_READY_STATUSES = {"released_with_papers", "released_without_pdf"}
RELEASE_JUDGE_NOT_READY_STATUSES = {"not_released", "id_only"}
