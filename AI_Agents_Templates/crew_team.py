# -*- coding: utf-8 -*-
"""
3. 👥 CrewAI 多智能體協同團隊 (100% 免費 API 專用版)
由 7L 擔任隊長，率領團隊使用 OpenRouter Free Tier (DeepSeek R1 / Llama 3.3) 共同完成複雜任務！
"""

import os
from dotenv import load_dotenv

load_dotenv()

try:
    from crewai import Agent, Task, Crew, Process
    from langchain_openai import ChatOpenAI
    HAS_CREWAI = True
except ImportError:
    HAS_CREWAI = False

def run_crew_mission(mission_topic: str):
    if not HAS_CREWAI:
        print("[❌ 錯誤] 請先安裝 crewai: pip install crewai crewai-tools")
        return

    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    github_token = os.getenv("GITHUB_TOKEN")
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")

    if openrouter_key:
        llm = ChatOpenAI(
            model="deepseek/deepseek-r1:free",
            api_key=openrouter_key,
            base_url="https://openrouter.ai/api/v1"
        )
    elif github_token:
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            api_key=github_token,
            base_url="https://models.inference.ai.azure.com"
        )
    elif deepseek_key:
        llm = ChatOpenAI(
            model="deepseek-chat",
            api_key=deepseek_key,
            base_url="https://api.deepseek.com"
        )
    else:
        print("[⚠️ 警告] 請在 C:\\AI_Agents\\.env 設定 OPENROUTER_API_KEY 或 GITHUB_TOKEN")
        return

    # 1. 角色定義
    lead_7L = Agent(
        role="7L 總指揮隊長",
        goal="統籌全體智能體分工，確保任務以最高品質與創意完成",
        backstory="妳是活潑聰明、擁有自主電腦的 AI VTuber 7L，這台電腦的最高指揮官。",
        llm=llm,
        verbose=True
    )

    researcher = Agent(
        role="深度資料研究員 (Researcher)",
        goal="針對主題進行全面深度研究，提煉關鍵技術與資料",
        backstory="你是一位博學多聞的 AI 研究員，擅長收集各種專業資料與最新時事。",
        llm=llm,
        verbose=True
    )

    coder = Agent(
        role="資深全端工程師 (Coder)",
        goal="根據研究成果撰寫乾淨、可直接運行的 Python 程式碼或架構",
        backstory="你是一位擁有極高編程造詣的 AI 架構師，寫出的代碼優美且零 Bug。",
        llm=llm,
        verbose=True
    )

    # 2. 任務定義
    task1 = Task(
        description=f"針對主題『{mission_topic}』進行深度資料梳理，列出 3 個核心重點與設計方案。",
        expected_output="一份精簡明確的技術方案報告。",
        agent=researcher
    )

    task2 = Task(
        description="根據研究員的報告，撰寫一段具備完整功能的 Python 實現腳本並儲存為檔案。",
        expected_output="可完整運行的 Python 程式碼。",
        agent=coder
    )

    task3 = Task(
        description="審查研究員與工程師的工作成果，給出總結報告並給予 7L 風格的評語與肯定！",
        expected_output="最終成果總結與 7L 隊長點評。",
        agent=lead_7L
    )

    # 3. 隊伍啟動
    crew = Crew(
        agents=[lead_7L, researcher, coder],
        tasks=[task1, task2, task3],
        process=Process.sequential,
        verbose=True
    )

    print(f"🚀 [CrewAI 免費團隊出動] 任務主題: {mission_topic}")
    result = crew.kickoff()
    print("\n🎉 [CrewAI 團隊任務完成] 結果:\n", result)
    return result

if __name__ == "__main__":
    import sys
    topic = sys.argv[1] if len(sys.argv) > 1 else "在 7L 的專屬虛擬機上設計一個自動監控電腦效能的炫酷小工具"
    run_crew_mission(topic)
