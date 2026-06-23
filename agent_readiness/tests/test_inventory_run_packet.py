import unittest
from pathlib import Path


class InventoryRunPacketTest(unittest.TestCase):

    def test_stock_packet_points_agent_to_site_and_output_files(self) -> None:
        from agent_readiness.inventory_run_packet import build_inventory_packet

        packet = build_inventory_packet(
            run_id="inventory-independent-001",
            copy_root=Path("/tmp/agent-readiness"),
            variant="stock",
        )

        self.assertEqual("inventory-independent-001", packet["run_id"])
        self.assertEqual("inventory.read_only", packet["task_id"])
        self.assertEqual("stock", packet["variant"])
        self.assertEqual(Path("/tmp/agent-readiness/inventory-independent-001/site"), packet["site_root"])
        self.assertEqual(Path("/tmp/agent-readiness/inventory-independent-001/answer.json"), packet["answer_json"])
        self.assertEqual(Path("/tmp/agent-readiness/inventory-independent-001/transcript.md"), packet["transcript"])
        self.assertIn("prompts/inventory.read_only.md", packet["prompt_text"])
        self.assertIn("/tmp/agent-readiness/inventory-independent-001/answer.json", packet["prompt_text"])

    def test_enhanced_packet_includes_site_architecture_artifact_paths(self) -> None:
        from agent_readiness.inventory_run_packet import build_inventory_packet

        packet = build_inventory_packet(
            run_id="inventory-enhanced-001",
            copy_root=Path("/tmp/agent-readiness"),
            variant="enhanced",
        )

        self.assertEqual("enhanced", packet["variant"])
        self.assertEqual(
            Path("/tmp/agent-readiness/inventory-enhanced-001/site-architecture-surfaces.json"),
            packet["enhanced_artifacts"]["surfaces_json"],
        )
        self.assertEqual(
            Path("/tmp/agent-readiness/inventory-enhanced-001/site-architecture-brief.md"),
            packet["enhanced_artifacts"]["brief_md"],
        )
        self.assertIn("site-architecture-brief.md", packet["prompt_text"])
        self.assertIn("site-architecture-surfaces.json", packet["prompt_text"])


if __name__ == "__main__":
    unittest.main()
