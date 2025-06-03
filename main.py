import streamlit as st
import sqlite3
import hashlib
from pathlib import Path
import google.generativeai as genai
import os
import json
import toml

# --- Configuração da API Gemini ---
if "GEMINI_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
else:
    st.error("Chave de API GEMINI não encontrada. Verifique .streamlit/secrets.toml ou a variável de ambiente GEMINI_API_KEY.")
    st.stop()

# Inicializa o modelo da IA para o site (verificação de jogo, download, geração de prompt)
model = genai.GenerativeModel('models/gemini-1.5-flash-latest') # Mantenha o nome que funcionou!

DB_PATH = Path(__file__).parent / "users.db"

# --- Banco de usuários ---
def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)
        conn.commit()
    except Exception as e:
        st.error(f"Erro ao inicializar o banco de dados: {e}")
    finally:
        conn.close()

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def register_user(email: str, password: str) -> bool:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO users (email, password_hash) VALUES (?, ?)",
            (email, hash_password(password))
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    except Exception as e:
        st.error(f"Erro ao registrar usuário: {e}")
        return False
    finally:
        conn.close()

def authenticate_user(email: str, password: str) -> bool:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT password_hash FROM users WHERE email = ?", (email,))
        row = c.fetchone()
        return row and row[0] == hash_password(password)
    except Exception as e:
        st.error(f"Erro ao autenticar usuário: {e}")
        return False
    finally:
        conn.close()

# --- Função de Verificação de Jogo com IA ---
def verify_game_with_ai(game_name: str) -> bool:
    try:
        prompt = f"O jogo '{game_name}' é um videogame conhecido e amplamente reconhecido? Responda apenas 'Sim' ou 'Não'."
        response = model.generate_content(prompt)
        if response and response.text:
            cleaned_response = response.text.strip().lower().replace('.', '')
            return "sim" in cleaned_response
        return False
    except Exception as e:
        st.error(f"Erro ao verificar o jogo com a IA: {e}")
        return False

# --- Obter Sugestão de Executável com IA (simplificado) ---
def get_game_exe_suggestion_with_ai(game_name: str):
    prompt = f"""Para o jogo '{game_name}', qual é o nome de arquivo executável mais comum (ex: 'game.exe', 'launcher.exe')?
    Responda APENAS o nome do arquivo executável, sem formatação extra, aspas ou explicações.
    Se não houver um executável óbvio ou for um jogo de console, responda "N/A".
    """
    try:
        response = model.generate_content(prompt)
        if response and response.text:
            cleaned_response = response.text.strip().replace('"', '')
            if cleaned_response.lower() == "não disponível":
                return "N/A"
            return cleaned_response
        return "N/A"
    except Exception as e:
        st.error(f"Erro ao obter sugestão de executável com a IA: {e}. Resposta da IA: {response.text if response else 'N/A'}")
        return "N/A"

# --- Gerar Prompt de Análise de Gameplay com IA ---
def generate_gameplay_analysis_prompt(game_name: str) -> str:
    try:
        ai_prompt_generator_instruction = f"""
        Você é um especialista em jogos. Sua tarefa é criar um prompt de instrução para uma IA analisar um frame de gameplay de um usuário.
        O prompt deve ser detalhado, focar em feedback técnico e específico para o jogo '{game_name}'.
        Inclua os seguintes pontos no prompt gerado:
        - Papel da IA (ex: "Você é um especialista em [Nome do Jogo]").
        - Tarefa da IA (ex: "Analise este frame de gameplay e forneça feedback técnico e específico.").
        - Focos de análise específicos:
            - Posicionamento do jogador (está bem posicionado ou exposto?).
            - Uso de habilidades, itens, ou recursos do jogo.
            - Priorização de inimigos/objetivos.
            - Gestão de recursos (vida, munição, etc.).
            - Erros comuns do jogador e como corrigi-los.
            - Dicas práticas e objetivas com exemplos concretos.

        O prompt final gerado pela IA deve ser APENAS o texto do prompt, sem formatação extra (como aspas de código), para ser diretamente usado em outra chamada à IA.
        """
        response = model.generate_content(ai_prompt_generator_instruction)
        if response and response.text:
            generated_prompt = response.text.strip()
            if generated_prompt.startswith('"') and generated_prompt.endswith('"'):
                generated_prompt = generated_prompt[1:-1]
            return generated_prompt
        return ""
    except Exception as e:
        st.error(f"Erro ao gerar o prompt de análise de gameplay com a IA: {e}")
        return ""

# --- Importa a função de análise de gameplay ---
from gameplay_analyzer import run_gameplay_analysis

# --- Lógica de sessão e telas ---
def main():
    try:
        init_db()

        if 'logged_in' not in st.session_state:
            st.session_state.logged_in = False
        if 'user_email' not in st.session_state:
            st.session_state.user_email = ""
        if 'game_selected' not in st.session_state:
            st.session_state.game_selected = False
        if 'current_game' not in st.session_state:
            st.session_state.current_game = ""
        # Remove download_method_selected, selected_platform.
        # Agora vamos direto para 'exe_input_received'
        if 'exe_input_received' not in st.session_state:
            st.session_state.exe_input_received = False
        if 'game_exe_name' not in st.session_state: # Novo estado para o nome do executável
            st.session_state.game_exe_name = ""
        if 'gameplay_analysis_prompt' not in st.session_state:
            st.session_state.gameplay_analysis_prompt = ""
        if 'analysis_report' not in st.session_state:
            st.session_state.analysis_report = ""
            
        if st.session_state.get("login_success"):
            st.session_state.pop("login_success")
            st.rerun()
            
        if 'analysis_started' not in st.session_state:
            st.session_state.analysis_started = False

        if not st.session_state.logged_in:
            show_auth_screen()
        elif not st.session_state.game_selected:
            show_game_selection()
        # Nova condição para pedir o executável
        elif not st.session_state.exe_input_received:
            show_exe_input_screen()
        elif not st.session_state.analysis_started:
            show_start_analysis_screen()
        else:
            show_analysis_results_screen()

    except Exception as e:
        st.error(f"Ocorreu um erro inesperado: {e}. Por favor, recarregue a página.")

def show_auth_screen():
    st.title("CONHEÇA O ME ENSINA A.I")
    st.write("""
    Em meio ao crescimento acelerado do universo gamer, um site brasileiro vem se destacando ao unir inteligência artificial e paixão por jogos. A plataforma foi criada com um propósito claro: ajudar jogadores de todos os níveis a melhorarem suas habilidades por meio de análises inteligentes e treinos personalizados com apoio de IA.
    Com ferramentas que analisam o desempenho em tempo real, o site oferece feedbacks estratégicos, dicas de posicionamento, tempo de reação, mira e tomada de decisão. Tudo isso baseado em dados precisos, o que torna o treinamento muito mais eficiente do que os métodos tradicionais.
    Essa inovação não só eleva o nível dos jogadores casuais, mas também abre portas para que mais talentos brasileiros cheguem ao cenário competitivo. O resultado é uma nova geração de gamers cada vez mais preparada e profissionalizada, contribuindo diretamente para o crescimento do público e da relevância dos eSports no Brasil.
    Combinando tecnologia de ponta com acessibilidade, essa plataforma está transformando o jeito de jogar — e o futuro dos jogos no país.
    """)

    tab1, tab2 = st.tabs(["Login", "Criar Conta"])
    with tab1:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Senha", type="password")
            login_btn = st.form_submit_button("Entrar")
            if login_btn:
                try:
                    if authenticate_user(email, password):
                        st.session_state.logged_in = True
                        st.session_state.user_email = email
                        st.session_state.login_success = True
                    else:
                        st.warning("Email ou senha inválidos.")
                except Exception as e:
                    st.error(f"Erro ao tentar fazer login: {e}. Tente novamente mais tarde.")

    with tab2:
        with st.form("signup_form"):
            new_email = st.text_input("Email de cadastro", key="signup_email")
            new_password = st.text_input("Senha", type="password", key="signup_pwd")
            pwd_confirm = st.text_input("Confirme a senha", type="password", key="signup_confirm")
            signup_btn = st.form_submit_button("Cadastrar")
            if signup_btn:
                try:
                    if not new_email or not new_password:
                        st.warning("Preencha todos os campos.")
                    elif new_password != pwd_confirm:
                        st.warning("As senhas devem ser iguais.")
                    else:
                        success = register_user(new_email, new_password)
                        if success:
                            st.success("Conta criada! Faça login para continuar.")
                        else:
                            st.warning("Já existe uma conta com esse email.")
                except Exception as e:
                    st.error(f"Erro ao tentar criar conta: {e}. Tente novamente mais tarde.")

def show_game_selection():
    try:
        st.title("Selecione o Jogo")
        st.write(f"Usuário: **{st.session_state.user_email}** \n")
        st.write("Digite o nome do jogo que você quer que a IA te ajude a melhorar:")

        game_name = st.text_input("Nome do Jogo")
        if st.button("Verificar Jogo"):
            if game_name.strip():
                with st.spinner("Verificando o jogo com a IA..."):
                    game_exists = verify_game_with_ai(game_name)

                if game_exists:
                    st.success(f"Jogo '{game_name}' encontrado!")
                    st.session_state.game_selected = True
                    st.session_state.current_game = game_name
                    # Não precisamos mais do download_method_selected, vamos direto para a entrada do EXE
                    st.session_state.exe_input_received = False # Reinicia para a próxima tela
                    st.rerun()
                else:
                    st.warning(f"O jogo '{game_name}' não foi encontrado. Por favor, digite outro nome.")
            else:
                st.warning("Por favor, digite o nome de um jogo.")
    except Exception as e:
        st.error(f"Erro ao processar o jogo: {e}. Tente novamente.")

# --- Nova tela para solicitar o nome do executável ---
def show_exe_input_screen():
    st.title("Informe o Executável do Jogo")
    st.write(f"Você selecionou o jogo: **{st.session_state.current_game}**.")
    st.write("Para iniciar a análise, precisamos do nome do arquivo executável principal do jogo (ex: `valorant.exe`, `cs2.exe`, `fortniteclient-win64-shipping.exe`).")

    suggested_exe = ""
    if 'suggested_exe_from_ai' not in st.session_state:
        with st.spinner(f"A IA está tentando sugerir um executável para '{st.session_state.current_game}'..."):
            suggested_exe = get_game_exe_suggestion_with_ai(st.session_state.current_game)
            st.session_state.suggested_exe_from_ai = suggested_exe
    else:
        suggested_exe = st.session_state.suggested_exe_from_ai

    if suggested_exe and suggested_exe != "N/A":
        st.info(f"Sugestão de executável para **{st.session_state.current_game}**: `{suggested_exe}`")
        initial_value = suggested_exe
    else:
        st.warning("Não foi possível obter uma sugestão de executável para este jogo. Por favor, insira o nome manualmente.")
        initial_value = ""

    game_exe_name = st.text_input(
        "Nome do arquivo executável (ex: `game.exe`)",
        value=initial_value,
        key="exe_input"
    )

    if st.button("Confirmar Executável e Gerar Análise"):
        if game_exe_name.strip() and game_exe_name.lower() != "n/a":
            st.session_state.game_exe_name = game_exe_name.strip()
            
            # Gera o prompt de análise de gameplay aqui
            with st.spinner("Gerando prompt de análise de gameplay personalizado..."):
                generated_prompt = generate_gameplay_analysis_prompt(st.session_state.current_game)
                if generated_prompt:
                    st.session_state.gameplay_analysis_prompt = generated_prompt
                    st.success("Prompt de análise gerado com sucesso!")
                else:
                    st.error("Não foi possível gerar um prompt de análise de gameplay. Tente novamente.")
                    # Se o prompt falhar, pode ser um problema, mas podemos tentar avançar.
                    # Considere adicionar uma verificação mais robusta aqui.
            
            st.session_state.exe_input_received = True
            st.session_state.analysis_started = False # Garante que a análise ainda não começou
            st.rerun()
        else:
            st.warning("Por favor, digite um nome de arquivo executável válido.")

    if st.button("Voltar para seleção de jogo"):
        st.session_state.game_selected = False
        st.session_state.exe_input_received = False
        st.session_state.current_game = ""
        st.session_state.suggested_exe_from_ai = "" # Limpa a sugestão anterior
        st.rerun()


# --- Nova tela para iniciar a análise ---
def show_start_analysis_screen():
    st.title("Inicie sua Análise de Gameplay")
    st.write(f"Jogo selecionado: **{st.session_state.current_game}**")
    st.write(f"Executável do jogo: **{st.session_state.game_exe_name}**")

    st.subheader("Instruções:")
    st.write("""
    1.  **Abra o jogo** (`""" + st.session_state.game_exe_name + """`) em **tela cheia** ou maximizado.
    2.  Certifique-se de que o jogo está visível na sua tela principal.
    3.  Clique no botão "Iniciar Análise de Gameplay" abaixo.
    """)

    # Exibir o prompt gerado (opcional, para depuração/visualização)
    if st.session_state.gameplay_analysis_prompt:
        with st.expander("Ver prompt de análise gerado (avançado)"):
            st.text_area("Prompt:", value=st.session_state.gameplay_analysis_prompt, height=150, disabled=True)
            st.caption("Este prompt será usado pela IA para analisar sua gameplay.")

    if st.button("Iniciar Análise de Gameplay", type="primary"):
        if not st.session_state.game_exe_name or st.session_state.game_exe_name == "N/A":
            st.error("Por favor, informe um executável válido para iniciar a análise.")
            return # Impede de prosseguir sem executável

        with st.spinner("Iniciando gravação e análise de gameplay... Por favor, jogue por alguns segundos."):
            # Chama a função principal de análise do gameplay_analyzer.py
            report = run_gameplay_analysis(
                jogo_alvo=st.session_state.game_exe_name,
                gameplay_prompt=st.session_state.gameplay_analysis_prompt,
                game_name=st.session_state.current_game
            )
            st.session_state.analysis_report = report
            st.session_state.analysis_started = True # Marca que a análise foi concluída
            st.rerun()
            
    if st.button("Voltar para inserir outro executável"):
        st.session_state.exe_input_received = False
        st.session_state.game_exe_name = ""
        st.session_state.suggested_exe_from_ai = ""
        st.rerun()

    if st.button("Sair"):
        st.session_state.clear()
        st.experimental_rerun()


# --- Nova tela para exibir os resultados da análise ---
def show_analysis_results_screen():
    st.title("Relatório de Análise de Gameplay")
    st.markdown("---")
    
    st.subheader(f"Jogo: {st.session_state.current_game}")
    st.write(f"Executável analisado: {st.session_state.game_exe_name}")
    
    if st.session_state.analysis_report:
        st.markdown(st.session_state.analysis_report)
    else:
        st.warning("Nenhum relatório de análise disponível. Algo pode ter dado errado durante a gravação ou processamento.")
        st.info("Verifique os logs no terminal para mais detalhes.")
        
    st.markdown("---")
    
    if st.button("Fazer nova análise para este jogo"):
        st.session_state.analysis_started = False
        st.session_state.analysis_report = ""
        st.rerun()
        
    if st.button("Escolher outro jogo"):
        st.session_state.clear()
        st.rerun()


if __name__ == "__main__":
    main()
