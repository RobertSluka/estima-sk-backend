"""feature_sets repository — named, versioned feature definitions per ML target."""


def get_or_create(
    cur,
    *,
    name: str,
    version: str,
    target: str,
    description: str | None = None,
    code_version: str | None = None,
) -> int:
    cur.execute(
        """
        INSERT INTO feature_sets (name, version, target, description, code_version)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (name, version, target) DO UPDATE SET
            description  = EXCLUDED.description,
            code_version = EXCLUDED.code_version
        RETURNING id
        """,
        (name, version, target, description, code_version),
    )
    return cur.fetchone()["id"]


def get_by_id(cur, feature_set_id: int) -> dict | None:
    cur.execute("SELECT * FROM feature_sets WHERE id = %s", (feature_set_id,))
    return cur.fetchone()
