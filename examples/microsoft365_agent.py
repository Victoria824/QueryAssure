"""Run the Microsoft 365 reference agent without a tenant or API key."""

from queryassure.microsoft365 import Microsoft365DemoHarness
from queryassure.workflows import WorkflowEvaluationRunner


def main() -> None:
    runner = WorkflowEvaluationRunner(Microsoft365DemoHarness())
    report = runner.run_file("evals/microsoft365.yml")
    for result in report["results"]:
        print(f"{result['case_id']}: {'PASS' if result['passed'] else 'FAIL'}")
    print(f"pass rate: {report['summary']['pass_rate']:.0%}")


if __name__ == "__main__":
    main()
