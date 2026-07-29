"""Neo4j-backed implementation of the `KnowledgeGraph` Protocol.

Schema follows the suggestion in `extensions.py`:

    (:Violation)-[:HAS_SEGMENT]->(:Segment)
    (:Violation)-[:CITES]->(:Article)
    (:Element)-[:OF]->(:Article)
    (:Segment)-[:SUPPORTS {strength}]->(:Element)
    (:Authority)-[:SUPPORTS]->(:Element)
    (:Violation)-[:CROSS_REFERENCES {relation}]->(:Violation)
    (:OpenQuestion)-[:BLOCKS]->(:Element)

Constraints are created on demand by `ensure_constraints()`. All writes use
MERGE so re-running the upsert is idempotent.
"""
from __future__ import annotations

from typing import Any

from .models import Violation


_CONSTRAINTS = [
    "CREATE CONSTRAINT violation_id IF NOT EXISTS FOR (v:Violation) REQUIRE v.violation_id IS UNIQUE",
    "CREATE CONSTRAINT segment_id IF NOT EXISTS FOR (s:Segment) REQUIRE s.segment_id IS UNIQUE",
    "CREATE CONSTRAINT article_id IF NOT EXISTS FOR (a:Article) REQUIRE a.article_id IS UNIQUE",
    "CREATE CONSTRAINT element_id IF NOT EXISTS FOR (e:Element) REQUIRE e.element_id IS UNIQUE",
    "CREATE CONSTRAINT authority_id IF NOT EXISTS FOR (a:Authority) REQUIRE a.authority_id IS UNIQUE",
    "CREATE CONSTRAINT open_question_id IF NOT EXISTS FOR (o:OpenQuestion) REQUIRE o.id IS UNIQUE",
]


class Neo4jKnowledgeGraph:
    """Implements `violation_pack.extensions.KnowledgeGraph`."""

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        driver: Any | None = None,
    ) -> None:
        try:
            from neo4j import GraphDatabase  # type: ignore
        except ImportError as exc:
            raise SystemExit(
                "neo4j is required. Install with: "
                "pip install -e '.[neo4j]'  (or: pip install neo4j)"
            ) from exc
        self.driver = driver or GraphDatabase.driver(uri, auth=(user, password))
        self.database = database
        self._constraints_done = False

    def close(self) -> None:
        self.driver.close()

    def __enter__(self) -> "Neo4jKnowledgeGraph":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ----------------------------------------------------------------- setup

    def ensure_database(self) -> None:
        """Create the target database if missing (Enterprise feature).
        No-op on Community Edition (the system DB rejects CREATE DATABASE)."""
        if self.database in ("neo4j", "system"):
            return
        try:
            with self.driver.session(database="system") as s:
                s.run(
                    f"CREATE DATABASE `{self.database}` IF NOT EXISTS"
                )
                s.run(f"START DATABASE `{self.database}`")
        except Exception:
            # Community edition or insufficient privileges — fall back to
            # the default database. Caller will see writes on `neo4j`.
            pass

    def reset_database(self) -> dict[str, int]:
        """Delete every node and relationship in the target database.
        Returns counts removed. ONLY affects `self.database`."""
        self.ensure_database()
        with self.driver.session(database=self.database) as s:
            before = list(s.run("MATCH (n) RETURN count(n) AS n"))[0]["n"]
            s.run("MATCH (n) DETACH DELETE n")
            after = list(s.run("MATCH (n) RETURN count(n) AS n"))[0]["n"]
        self._constraints_done = False
        self.ensure_constraints()
        return {"nodes_before": before, "nodes_after": after}

    def ensure_constraints(self) -> None:
        if self._constraints_done:
            return
        self.ensure_database()
        with self.driver.session(database=self.database) as s:
            for c in _CONSTRAINTS:
                s.run(c)
        self._constraints_done = True

    def _run(self, query: str, **params: Any) -> list[dict]:
        with self.driver.session(database=self.database) as s:
            return [r.data() for r in s.run(query, **params)]

    # -------------------------------------------------------- KG operations

    def upsert_violation(self, violation: Violation) -> None:
        self.ensure_constraints()
        v = violation
        self._run(
            """
            MERGE (vi:Violation {violation_id: $vid})
              SET vi.title = $title,
                  vi.severity = $severity,
                  vi.schema_version = $schema
            """,
            vid=v.violation_id,
            title=v.title,
            severity=v.severity,
            schema=v.schema_version,
        )

        # Segments
        for seg in v.segments:
            self._run(
                """
                MERGE (s:Segment {segment_id: $sid})
                  SET s.role_in_argument = $role,
                      s.audio_offset_start = $start,
                      s.audio_offset_end = $end,
                      s.speaker = $speaker,
                      s.source_uri = $uri
                WITH s
                MATCH (vi:Violation {violation_id: $vid})
                MERGE (vi)-[:HAS_SEGMENT]->(s)
                """,
                sid=seg.segment_id,
                role=seg.role_in_argument,
                start=seg.audio_offset_start,
                end=seg.audio_offset_end,
                speaker=seg.speaker,
                uri=seg.source_uri,
                vid=v.violation_id,
            )

        # Articles
        for art in v.established_articles:
            self._run(
                """
                MERGE (a:Article {article_id: $aid})
                  SET a.article_name = $name,
                      a.framework_code = $fw,
                      a.duty_bearer = $duty,
                      a.norm_type = $norm
                WITH a
                MATCH (vi:Violation {violation_id: $vid})
                MERGE (vi)-[:CITES]->(a)
                """,
                aid=art.article_id,
                name=art.article_name,
                fw=art.framework_code,
                duty=art.duty_bearer,
                norm=art.norm_type,
                vid=v.violation_id,
            )

        # Element grids → Element nodes attached to Articles
        for grid in v.element_grids:
            for el in grid.elements:
                self._run(
                    """
                    MERGE (e:Element {element_id: $eid})
                      SET e.label = $label,
                          e.proof_status = $status
                    WITH e
                    MATCH (a:Article {article_id: $aid})
                    MERGE (e)-[:OF]->(a)
                    """,
                    eid=el.element_id,
                    label=el.label,
                    status=el.proof_status,
                    aid=grid.article_id,
                )
                for seg_id in el.proof_evidence_segments:
                    self._run(
                        """
                        MATCH (s:Segment {segment_id: $sid})
                        MATCH (e:Element {element_id: $eid})
                        MERGE (s)-[r:SUPPORTS]->(e)
                        """,
                        sid=seg_id,
                        eid=el.element_id,
                    )

        # Nexus edges carry the explicit strength
        for nx in v.nexus_matrix:
            self._run(
                """
                MATCH (s:Segment {segment_id: $sid})
                MATCH (e:Element {element_id: $eid})
                MERGE (s)-[r:SUPPORTS]->(e)
                  SET r.strength = $strength,
                      r.nexus_type = $type,
                      r.rationale = $rat
                """,
                sid=nx.fact_id,
                eid=nx.element_id,
                strength=nx.strength,
                type=nx.nexus_type,
                rat=nx.rationale_oneline,
            )

        # Authorities (no court/rol set unless verified=True — preserved)
        for auth in v.authorities:
            self._run(
                """
                MERGE (au:Authority {authority_id: $aid})
                  SET au.type = $type,
                      au.verified = $verified,
                      au.research_query = $q,
                      au.proposition_to_verify = $prop,
                      au.court = $court,
                      au.rol = $rol,
                      au.holding_summary = $holding
                """,
                aid=auth.authority_id,
                type=auth.type,
                verified=auth.verified,
                q=auth.research_query,
                prop=auth.proposition_to_verify,
                court=auth.court,
                rol=auth.rol,
                holding=auth.holding_summary,
            )
            for el_id in auth.supports:
                self._run(
                    """
                    MATCH (au:Authority {authority_id: $aid})
                    MATCH (e:Element {element_id: $eid})
                    MERGE (au)-[:SUPPORTS]->(e)
                    """,
                    aid=auth.authority_id,
                    eid=el_id,
                )

        # Open questions
        for oq in v.open_questions:
            self._run(
                """
                MERGE (o:OpenQuestion {id: $oid})
                  SET o.question = $q,
                      o.priority = $prio
                """,
                oid=oq.id,
                q=oq.question,
                prio=oq.priority,
            )
            if oq.blocks_element:
                self._run(
                    """
                    MATCH (o:OpenQuestion {id: $oid})
                    MATCH (e:Element {element_id: $eid})
                    MERGE (o)-[:BLOCKS]->(e)
                    """,
                    oid=oq.id,
                    eid=oq.blocks_element,
                )

        self.link_cross_references(v)

    def link_cross_references(self, violation: Violation) -> None:
        self.ensure_constraints()
        for ref in violation.cross_references:
            self._run(
                """
                MERGE (a:Violation {violation_id: $a})
                MERGE (b:Violation {violation_id: $b})
                MERGE (a)-[r:CROSS_REFERENCES]->(b)
                  SET r.relation = $rel
                """,
                a=violation.violation_id,
                b=ref.ref,
                rel=ref.relation,
            )

    def find_violations_citing(self, article_id: str) -> list[str]:
        rows = self._run(
            """
            MATCH (v:Violation)-[:CITES]->(a:Article {article_id: $aid})
            RETURN v.violation_id AS vid
            ORDER BY vid
            """,
            aid=article_id,
        )
        return [r["vid"] for r in rows]

    def find_violations_with_contested_element(
        self, element_id_glob: str
    ) -> list[str]:
        # Treat '*' as wildcard; emit a regex match.
        regex = "^" + element_id_glob.replace(".", r"\.").replace("*", ".*") + "$"
        rows = self._run(
            """
            MATCH (e:Element)-[:OF]->(:Article)<-[:CITES]-(v:Violation)
            WHERE e.element_id =~ $rx AND e.proof_status = 'contested'
            RETURN DISTINCT v.violation_id AS vid
            ORDER BY vid
            """,
            rx=regex,
        )
        return [r["vid"] for r in rows]

    def walk_implications_of_open_question(
        self, open_question_id: str
    ) -> list[dict]:
        rows = self._run(
            """
            MATCH (o:OpenQuestion {id: $oid})-[:BLOCKS]->(e:Element)-[:OF]->(a:Article)
            OPTIONAL MATCH (v:Violation)-[:CITES]->(a)
            RETURN DISTINCT
                e.element_id    AS element_id,
                e.proof_status  AS proof_status,
                a.article_id    AS article_id,
                v.violation_id  AS violation_id
            ORDER BY violation_id, article_id, element_id
            """,
            oid=open_question_id,
        )
        return rows
