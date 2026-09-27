"""Synthetic bare-act-style pages for tests.

This is NOT real legal text. It only imitates the *layout* of an India Code bare act (running
header, arrangement of sections, "CHAPTER <roman>" headings, "N. Title.—" section headings,
sub-sections, clauses, Explanations, Illustrations, a schedule) with placeholder wording.
"""

from app.services.ingestion.types import PageText

HEADER = "THE PLACEHOLDER SANHITA, 0000"

FAKE_ACT_PAGES = [
    PageText(
        1,
        f"""{HEADER}
ARRANGEMENT OF SECTIONS
CHAPTER I
PRELIMINARY
1. Placeholder short title.
2. Placeholder definitions.
CHAPTER II
OF PLACEHOLDER MATTERS
3. Placeholder rule alpha.
4A. Placeholder rule beta.
THE FIRST SCHEDULE.
1""",
    ),
    PageText(
        2,
        f"""{HEADER}
THE PLACEHOLDER SANHITA, 0000
An Act to illustrate placeholder layout only.
CHAPTER I
PRELIMINARY
1. Placeholder short title.—(1) This Placeholder may be called the Placeholder Sanhita.
(2) It applies to nothing and nobody.
2. Placeholder definitions.—In this Placeholder, unless the context otherwise requires,—
(a) "widget" means a placeholder object;
(b) "gadget" means another placeholder object.
2""",
    ),
    PageText(
        3,
        f"""{HEADER}
CHAPTER II
OF PLACEHOLDER MATTERS
3. Placeholder rule alpha.—Whoever does a placeholder act shall be liable to a place-
holder consequence.
Explanation.—A placeholder act is any act described in this fake fixture.
Illustration
A does a placeholder act. A is liable under this placeholder rule.
3""",
    ),
    PageText(
        4,
        f"""{HEADER}
4A. Placeholder rule beta with a heading that wraps
onto a second line.—Whoever does a second placeholder act shall be liable.
CHAPTER III—OF MORE PLACEHOLDERS
5. Placeholder rule gamma.–Text with an en dash separator.
6. Placeholder rule delta.--Text with an ASCII double hyphen separator.
THE FIRST SCHEDULE
7. This schedule entry is not a section.—It must not become a chunk.
4""",
    ),
]
