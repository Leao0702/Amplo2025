import os
import sys

# Garante que o script rode no mesmo diretório do .exe
os.chdir(os.path.dirname(sys.executable))  # ← pega a pasta onde o EXE será executado

# Chama o Streamlit com seu painel
os.system("streamlit run \"API AMPLO WEB.py\"")
