import unittest

import server


class PasswordTests(unittest.TestCase):
    def test_scrypt_hash_verifies_password(self):
        encoded = server.password_hash("A-secure-demo-password")
        self.assertTrue(server.password_matches("A-secure-demo-password", encoded))
        self.assertFalse(server.password_matches("wrong-password", encoded))


class ValidationTests(unittest.TestCase):
    def test_report_text_is_trimmed(self):
        self.assertEqual(server.Handler.clean_text("  streetlight  ", "Title", 5, 40), "streetlight")

    def test_report_text_rejects_too_short_values(self):
        with self.assertRaises(server.AppError):
            server.Handler.clean_text("no", "Title", 5, 40)

    def test_coordinate_range_is_enforced(self):
        self.assertEqual(server.Handler.optional_coordinate("12.4", -90, 90), 12.4)
        with self.assertRaises(server.AppError):
            server.Handler.optional_coordinate("181", -90, 90)

    def test_trustshield_reports_explainable_rules_not_confidence(self):
        row = {
            "description": "A damaged crossing is difficult to use.",
            "category": "Accessibility",
            "location": "Main entrance",
            "evidence_note": "",
            "status": "AWAITING_VERIFICATION",
        }
        result = server.Handler.trustshield(row)
        self.assertEqual(result["mode"], "rules-based demo")
        self.assertTrue(result["review_required"])
        self.assertNotIn("confidence", result)
        self.assertEqual(len(result["signals"]), 4)


class PrivacyTests(unittest.TestCase):
    def test_coordinates_remain_hidden_until_reporter_opts_in(self):
        report = {
            "latitude": 12.5,
            "longitude": 77.6,
            "coordinates_shared": 0,
            "user_id": 15,
            "assigned_to": 23,
            "description": "The sidewalk is cracked beside the public crossing.",
            "category": "Accessibility",
            "location": "Main entrance",
            "evidence_note": "",
            "status": "AWAITING_VERIFICATION",
        }
        result = server.Handler.report_json(report, {"role": "platform_admin"})
        self.assertIsNone(result["latitude"])
        self.assertIsNone(result["longitude"])

        report["coordinates_shared"] = 1
        result = server.Handler.report_json(report, {"role": "platform_admin"})
        self.assertEqual(result["latitude"], 12.5)
        self.assertEqual(result["longitude"], 77.6)

    def test_coordinates_are_only_visible_to_the_assigned_resolver(self):
        report = {
            "latitude": 12.5,
            "longitude": 77.6,
            "coordinates_shared": 1,
            "user_id": 15,
            "assigned_to": 23,
            "description": "The sidewalk is cracked beside the public crossing.",
            "category": "Accessibility",
            "location": "Main entrance",
            "evidence_note": "",
            "status": "ASSIGNED",
        }
        other_resolver = server.Handler.report_json(report, {"role": "resolver", "id": 24})
        assigned_resolver = server.Handler.report_json(report, {"role": "resolver", "id": 23})
        self.assertIsNone(other_resolver["latitude"])
        self.assertEqual(assigned_resolver["latitude"], 12.5)


if __name__ == "__main__":
    unittest.main()
