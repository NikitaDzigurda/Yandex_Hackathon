from deep_research import run_deep_research, print_summary

project = """
HISTOSCAN — комплекс программных продуктов для врачей-патологов.
Есть on-premise и облачная версии.
Нужно спланировать дальнейшее развитие продукта и подготовить пакет для разработки.
"""

result = run_deep_research(
    project_description=project,
    tracker_context="",
    source_craft_context="",
    artifact_dir="deep_research_output",
    print_agent_outputs=True,
)

print_summary(result)