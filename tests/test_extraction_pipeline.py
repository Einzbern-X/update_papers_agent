import unittest

try:
    import yaml  # noqa: F401
    from agent.extraction_pipeline import ExtractionAttempt, ExtractionPipeline
except ModuleNotFoundError as exc:
    ExtractionAttempt = None
    ExtractionPipeline = None
    MISSING_DEPENDENCY = exc.name
else:
    MISSING_DEPENDENCY = ""


class _Logger:
    def info(self, *_args):
        pass

    def warning(self, *_args):
        pass


class _LLMClient:
    def available(self):
        return False


@unittest.skipIf(ExtractionPipeline is None, f"missing dependency: {MISSING_DEPENDENCY}")
class ExtractionPipelineBehaviorTest(unittest.TestCase):
    def test_variable_pipeline_stops_after_first_valid_strategy(self):
        pipeline = ExtractionPipeline(
            llm_client=_LLMClient(),
            llm_cfg={},
            agent_cfg={"auto_generate_rules": False},
            detail_enricher=None,
            logger=_Logger(),
        )
        calls = []

        def saved_script(_source, _html):
            calls.append("saved_script")
            return ExtractionAttempt([{"title": "A Reliable Parser"}], True, "ok", "released_saved_script")

        def saved_rule(_source, _html):
            calls.append("saved_rule")
            return ExtractionAttempt([], False, "should_not_run")

        def fixed_parser(_source, _html):
            calls.append("fixed_parser")
            return ExtractionAttempt([], False, "should_not_run")

        pipeline.try_saved_script = saved_script
        pipeline.try_saved_rule = saved_rule
        pipeline.try_fixed_parser = fixed_parser

        result = pipeline.extract_variable({}, "<html></html>", {})

        self.assertTrue(result.valid)
        self.assertEqual(result.status, "released_saved_script")
        self.assertEqual(calls, ["saved_script"])


if __name__ == "__main__":
    unittest.main()
