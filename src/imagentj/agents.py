import os
from deepagents import create_deep_agent
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from .prompts import imagej_coder_prompt, imagej_debugger_prompt, supervisor_prompt, python_analyst_prompt
from .tools import internet_search, inspect_all_ui_windows, run_script_safe, rag_retrieve_docs, inspect_java_class, save_coding_experience, rag_retrieve_mistakes, save_reusable_script, inspect_folder_tree, smart_file_reader, run_python_code, inspect_csv_header, extract_image_metadata, search_fiji_plugins, install_fiji_plugin, check_plugin_installed, mkdir_copy, save_script, execute_script, get_script_info
from .tools import load_script, get_script_history

gpt_key = os.getenv("OPENAI_API_KEY")

checkpointer_supervisor = MemorySaver()
checkpointer_imagej_coder = MemorySaver()
checkpointer_imagej_debugger = MemorySaver()
checkpointer_python_analyst = MemorySaver()

llm_gpt5 = ChatOpenAI(
    model = "gpt-5.2",
    verbose=True,
    api_key=gpt_key,
    temperature=0.,
    reasoning_effort="low",
)

llm_gpt5_nano = ChatOpenAI(
    model = "gpt-5.2",
    verbose=True,
    api_key=gpt_key,
    temperature=0.,
    reasoning_effort="low",
)

imagej_coder = {
    "name": "imagej_coder",

    "description": """Generates production-ready ImageJ/Fiji code (Groovy) and manages its integration into the project repository. 
                    The agent is responsible for writing scripts via 'save_script' (including detailed functional documentation for the Supervisor), 
                    reviewing existing project code with 'load_script', and consulting 'get_script_history' to avoid repeating failures. 
                    It must ALWAYS report the absolute path of the saved script as its final output.""",

    "system_prompt": imagej_coder_prompt,
    "middleware":[],
    "tools": [internet_search, inspect_java_class, save_script, load_script, get_script_history],
    "model":llm_gpt5_nano,
    "checkpointer":checkpointer_imagej_coder,
}



imagej_debugger = {
    "name": "imagej_debugger",
    "description": """Diagnoses and repairs ImageJ/Fiji scripts (Groovy) that fail during execution. 
                    It uses 'load_script' to retrieve the faulty code and 'get_script_history' to avoid 
                    repeating unsuccessful fixes. It applies surgical corrections, preservation of intent, 
                    and ensures compliance with ImageJ constraints. The agent commits the fix via 
                    'save_script', providing the 'error_context' to update the versioned history, 
                    and reports the absolute path of the repaired script.""",

    "system_prompt": imagej_debugger_prompt,
    "tools": [internet_search, inspect_java_class, rag_retrieve_mistakes, save_script, load_script, get_script_history, get_script_info],
    "model":llm_gpt5_nano,
    "middleware":[],
    "checkpointer":checkpointer_imagej_debugger,
}   


python_data_analyst = {
    "name": "python_data_analyst",
    "description": """Expert in biological statistics and publication-quality plotting. 
                    Uses Pandas, Scipy, and Seaborn to analyze ImageJ CSV outputs. 
                    Manages Python scripts via 'save_script', 'load_script', and 'get_script_history' 
                    to maintain a modular, versioned analysis pipeline. Performs 
                    rigorous hypothesis testing (Stage 1) and generates 300 DPI plots (Stage 2) 
                    while documenting statistical assumptions in the project dictionary.""",
    "system_prompt": python_analyst_prompt,
    "tools": [inspect_csv_header, save_script, load_script, get_script_history, load_script, get_script_info],
    "model": llm_gpt5, 
    "middleware": [],
    "checkpointer": checkpointer_python_analyst,
}



def init_agent():

    supervisor = create_deep_agent(
    name="ImageJ_Supervisor",
    tools = [internet_search, inspect_all_ui_windows, rag_retrieve_docs, save_coding_experience, rag_retrieve_mistakes, save_reusable_script, inspect_folder_tree, smart_file_reader, extract_image_metadata, search_fiji_plugins, install_fiji_plugin, check_plugin_installed, mkdir_copy, inspect_csv_header, execute_script, get_script_info],
    system_prompt=supervisor_prompt,
    subagents=[imagej_coder, imagej_debugger, python_data_analyst],
    middleware=[],
    model=llm_gpt5,
    debug=False,
    checkpointer=checkpointer_supervisor,
)
    return supervisor, checkpointer_supervisor