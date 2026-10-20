"""Query/document categories (snake_case enum shared by ingestion, retrieval and the classifier)."""

from enum import Enum


class Category(str, Enum):
    PROGRAM_POLICIES = "program_policies"
    INCENTIVE_REBATE = "incentive_rebate"
    BILLING_ACCOUNT = "billing_account"
    TECHNICAL_INSTALLATION = "technical_installation"
    COMPANY_UPDATES = "company_updates"
    NON_RELEVANT = "non_relevant"


# Categories a document can carry. `non_relevant` only ever labels queries.
DOC_CATEGORIES = [c for c in Category if c is not Category.NON_RELEVANT]
