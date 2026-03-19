from django.test import SimpleTestCase

from core.job_filter.pipeline_debug import JobPreFilter, PipelineDebugReport
from core.job_filter.user_job_relevance import UserJobRelevanceScorer


class UserJobRelevanceScorerTests(SimpleTestCase):
	def setUp(self) -> None:
		self.user_profile = {
			"skills": ["Python", "Django", "AWS", "SQL"],
			"experience": 5,
			"preferred_roles": ["Backend Developer", "Python Engineer"],
			"location": "Remote",
		}

	def test_scale_10_saves_when_score_above_threshold(self) -> None:
		scorer = UserJobRelevanceScorer(user_profile=self.user_profile, scale=10)
		result = scorer.evaluate(
			{
				"title": "Senior Python Backend Developer",
				"description": "Looking for Python, Django, SQL and AWS skills with 4 years experience.",
				"required_skills": ["python", "django", "sql", "aws"],
				"experience_required": 4,
				"location": "Remote",
			}
		)

		self.assertGreater(result["score"], 6)
		self.assertEqual(result["decision"], "SAVE")
		self.assertIn("python", result["matched_skills"])

	def test_scale_10_discards_when_below_threshold(self) -> None:
		scorer = UserJobRelevanceScorer(user_profile=self.user_profile, scale=10)
		result = scorer.evaluate(
			{
				"title": "iOS Swift Engineer",
				"description": "Need Swift and Objective-C developer in office.",
				"required_skills": ["swift", "objective-c"],
				"experience_required": 8,
				"location": "On-site Berlin",
			}
		)

		self.assertLessEqual(result["score"], 6)
		self.assertEqual(result["decision"], "DISCARD")
		self.assertIn("swift", result["missing_skills"])

	def test_scale_5_threshold_rule(self) -> None:
		scorer = UserJobRelevanceScorer(user_profile=self.user_profile, scale=5)
		result = scorer.evaluate(
			{
				"title": "Python API Engineer",
				"description": "Build APIs in Django with SQL and cloud deployment.",
				"required_skills": ["python", "django", "sql"],
				"experience_required": 5,
				"location": "Remote",
			}
		)

		self.assertGreater(result["score"], 3)
		self.assertEqual(result["decision"], "SAVE")

	def test_no_high_score_without_strong_skill_match(self) -> None:
		scorer = UserJobRelevanceScorer(user_profile=self.user_profile, scale=10)
		result = scorer.evaluate(
			{
				"title": "Project Manager",
				"description": "Manage roadmap and stakeholder communication.",
				"required_skills": ["jira", "roadmapping", "stakeholder communication"],
				"experience_required": 5,
				"location": "Remote",
			}
		)

		self.assertLessEqual(result["score"], 6)
		self.assertEqual(result["decision"], "DISCARD")

	def test_custom_threshold_changes_save_decision(self) -> None:
		scorer = UserJobRelevanceScorer(
			user_profile=self.user_profile,
			scale=10,
			threshold=9.5,
		)
		result = scorer.evaluate(
			{
				"title": "Python Backend Developer",
				"description": "Need Python and Django with SQL skills for backend APIs.",
				"required_skills": ["python", "django", "sql"],
				"experience_required": 5,
				"location": "Remote",
			}
		)

		self.assertLessEqual(result["score"], 9.5)
		self.assertEqual(result["decision"], "DISCARD")


class PipelineDebugReportTests(SimpleTestCase):
	def test_prefilter_removes_irrelevant_job(self) -> None:
		prefilter = JobPreFilter(
			{
				"skills": ["python", "django"],
				"preferred_roles": ["backend developer"],
			}
		)

		should_score, reason = prefilter.should_score(
			{
				"title": "iOS Engineer",
				"description": "Swift mobile development role.",
				"required_skills": ["swift"],
				"location": "Berlin",
			}
		)

		self.assertFalse(should_score)
		self.assertEqual(reason, "prefilter_removed")

	def test_distribution_and_message_render(self) -> None:
		report = PipelineDebugReport(scale=10, threshold=6, debug_mode=False)
		report.record_scraped(12)
		report.record_prefilter(True)
		report.record_prefilter(False, "prefilter_removed")
		report.record_scored_job(
			title="Backend Developer",
			score=7.4,
			matched_skills=["python", "django"],
			missing_skills=[],
			passed_threshold=True,
			saved=True,
			reasons=[],
		)
		report.record_scored_job(
			title="Data Analyst",
			score=5.9,
			matched_skills=["sql"],
			missing_skills=["python"],
			passed_threshold=False,
			saved=False,
			reasons=["low_score", "missing_skills"],
		)

		payload = report.to_payload()
		self.assertEqual(payload["score_distribution"]["7-8"], 1)
		self.assertEqual(payload["score_distribution"]["5-6"], 1)
		self.assertEqual(payload["rejected_reasons"]["prefilter_removed"], 1)
		self.assertEqual(payload["rejected_reasons"]["low_score"], 1)

		message = report.build_telegram_message()
		self.assertIn("Job Debug Report", message)
		self.assertIn("Backend Developer", message)
		self.assertIn("Data Analyst", message)
