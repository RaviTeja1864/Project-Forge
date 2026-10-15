import uuid

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class WorkspaceArtifactVersionMigrationTests(TransactionTestCase):
    migrate_from = ("workspaces", "0005_workspaceartifact_input_artifact_ids_and_more")
    migrate_to = ("workspaces", "0006_workspaceartifact_author_and_more")

    def test_existing_artifacts_become_first_versions_without_losing_provenance(self):
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        try:
            old_apps = executor.loader.project_state([self.migrate_from]).apps
            workspace_model = old_apps.get_model("workspaces", "ProjectWorkspace")
            artifact_model = old_apps.get_model("workspaces", "WorkspaceArtifact")

            owner = get_user_model().objects.create_user(
                email="version-migration@example.com",
                password="test-password-only",
            )
            workspace = workspace_model.objects.create(
                owner_id=owner.pk,
                name="Migration fixture",
            )
            artifact_id = uuid.uuid4()
            content = {"problem_summary": "Legacy content remains unchanged."}
            snapshot = [
                {"id": "legacy-source-id", "source_url": "https://example.org/source"}
            ]
            artifact_model.objects.create(
                id=artifact_id,
                workspace_id=workspace.pk,
                kind="research",
                status="approved",
                content=content,
                source_snapshot=snapshot,
                source_problem_id=uuid.uuid4(),
                input_artifact_ids=[],
            )

            executor = MigrationExecutor(connection)
            executor.migrate([self.migrate_to])
            versioned_apps = executor.loader.project_state([self.migrate_to]).apps
            versioned_artifact = versioned_apps.get_model(
                "workspaces", "WorkspaceArtifact"
            ).objects.get(pk=artifact_id)
            self.assertEqual(versioned_artifact.version_number, 1)
            self.assertEqual(versioned_artifact.lineage_root_id, artifact_id)
            self.assertIsNone(versioned_artifact.revision_of_id)
            self.assertIsNone(versioned_artifact.author_id)
            self.assertEqual(versioned_artifact.status, "approved")
            self.assertEqual(versioned_artifact.content, content)
            self.assertEqual(versioned_artifact.source_snapshot, snapshot)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
