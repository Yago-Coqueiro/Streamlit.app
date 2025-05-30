import streamlit as st
import cv2
import numpy as np
from mss import mss
import time
from datetime import datetime
import subprocess
import os
import requests
import base64
from PIL import Image
import io
import warnings
import json
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import google.generativeai as genai

# Suppress warnings for cleaner output
warnings.filterwarnings("ignore")

# --- Variáveis Globais de Configuração (Padrões) ---
# Elas serão sobrescritas pelos argumentos da função run_gameplay_analysis
monitor_settings = {
    "top": 0,
    "left": 0,
    "width": 1920,
    "height": 1080
}
fps = 10.0

# As chaves de API devem ser carregadas de forma segura em ambiente de produção.
# Para teste local, podem estar aqui, mas cuidado ao subir para repositórios públicos.
# OPENROUTER_API_KEY e GEMINI_API_KEY serão passadas como st.secrets no fds.py,
# mas se este script for executado standalone, elas precisariam ser definidas aqui ou via variáveis de ambiente.
# Por simplicidade e para integração com Streamlit, o fds.py irá lidar com a passagem das chaves.
# No entanto, a API Key do Gemini para `genai.GenerativeModel` PRECISA ser configurada.
# O Ideal é configurar aqui APENAS a chave Gemini para o `genai.GenerativeModel`
# que será usado para sintetizar as dicas, se ele for diferente do Gemini do fds.py.
# Como o Gemini usado para síntese é o 'gemini-2.0-flash' e o do fds.py pode ser diferente,
# configuramos aqui com a mesma chave, assumindo que ela é válida para ambos.
#
# Se você tiver um problema de cota com o 'gemini-2.0-flash' na síntese, ele pode
# estar atingindo cotas separadas do 'gemini-1.5-flash-latest' que você usa no fds.py.
# A melhor prática seria passar as chaves como argumentos da função.

# --- APIs - Certifique-se que estas chaves são as suas chaves REAIS, NÃO as dummy ---
# Nota: Para o Streamlit Cloud, o fds.py cuidará de passar as chaves de forma segura.
# Aqui, mantemos as chaves para se este script for executado de forma independente.
OPENROUTER_API_KEY = "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" # A chave do seu exemplo
GEMINI_API_KEY = 'AIzaSyBco-5bq8-o_0adSTuktqf6c8-xui0hDcU' # A chave do seu exemplo

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "meta-llama/llama-3.2-11b-vision-instruct:free"

# Configure Gemini para a síntese de dicas
genai.configure(api_key=GEMINI_API_KEY)


def jogo_esta_rodando(jogo_alvo_exe: str) -> bool:
    """Check if the target game is running."""
    if not jogo_alvo_exe or jogo_alvo_exe == "Não disponível":
        # Se não houver um executável alvo, não podemos verificar se está rodando
        # Mas podemos assumir que o usuário vai rodar o jogo e capturar a tela.
        # Para um sistema robusto, isso deveria ser um erro ou requerer confirmação manual.
        return True # Assumimos que o jogo está rodando se não houver EXE alvo
    try:
        output = os.popen('tasklist').read()
        return jogo_alvo_exe.lower() in output.lower()
    except Exception as e:
        print(f"Erro ao verificar processo do jogo: {e}")
        return False

def capturar_tela(sct, monitor):
    """Capture the screen with robust error handling."""
    try:
        screenshot = sct.grab(monitor)
        if not screenshot:
            print("⚠️ A captura retornou None")
            return None
        frame = np.array(screenshot)
        if frame.size == 0:
            print("⚠️ Frame vazio capturado")
            return None
        return frame
    except Exception as e:
        print(f"❌ Erro na captura: {str(e)}")
        return None

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.HTTPError))
)
def make_openrouter_request(url, headers, payload, timeout):
    """Make a request to OpenRouter with retry logic."""
    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    # Adicionar log do status code e response text para depuração
    if response.status_code != 200:
        print(f"OpenRouter HTTP Error: {response.status_code} - {response.text}")
    response.raise_for_status() # Lança exceção para status codes de erro
    return response

def analyze_gameplay_with_llama(frames, gameplay_prompt: str, sample_size=5):
    """Analyze gameplay frames using Llama via OpenRouter."""
    tips = []
    # Usando st.session_state.gameplay_analysis_prompt que foi passado
    if not gameplay_prompt:
        return ["Erro: Prompt de análise de gameplay não fornecido. A IA não pode analisar."]

    if not OPENROUTER_API_KEY or len(OPENROUTER_API_KEY) < 20:
        return ["Erro: Chave de API do OpenRouter inválida ou muito curta"]

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    # Select diverse frames (e.g., evenly spaced)
    total_frames = len(frames)
    step = max(1, total_frames // sample_size)
    selected_frames = [frames[i * step] for i in range(min(sample_size, total_frames // step))]

    for i, frame in enumerate(selected_frames):
        try:
            # Convert frame to base64
            img_pil = Image.fromarray(frame)
            buffered = io.BytesIO()
            img_pil.save(buffered, format="JPEG", quality=85)
            base64_image = base64.b64encode(buffered.getvalue()).decode('utf-8')

            payload = {
                "model": OPENROUTER_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": gameplay_prompt}, # USA O PROMPT GERADO AQUI!
                            {"type": "image_url", "image_url": f"data:image/jpeg;base64,{base64_image}"}
                        ]
                    }
                ],
                "max_tokens": 500
            }

            response = make_openrouter_request(OPENROUTER_API_URL, headers, payload, timeout=30)
            data = response.json()
            
            # Verifique se 'choices' e 'message' existem na resposta
            if 'choices' in data and len(data['choices']) > 0 and 'message' in data['choices'][0]:
                tip = data['choices'][0]['message']['content']
                tips.append(f"Frame {i+1}: {tip}")
            else:
                tips.append(f"Frame {i+1}: Resposta inesperada da API: {data}")

        except requests.exceptions.HTTPError as http_err:
            tips.append(f"Frame {i+1}: Erro HTTP - {str(http_err)} - Detalhes: {http_err.response.text if http_err.response else 'N/A'}")
        except requests.exceptions.ConnectionError as conn_err:
            tips.append(f"Frame {i+1}: Erro de conexão - Verifique sua internet ou DNS ({str(conn_err)})")
        except requests.exceptions.Timeout:
            tips.append(f"Frame {i+1}: Timeout na conexão com a API")
        except (KeyError, json.JSONDecodeError) as parse_err:
            tips.append(f"Frame {i+1}: Resposta inválida da API (JSON/KeyError): {parse_err}. Resposta bruta: {response.text[:200] if 'response' in locals() else 'N/A'}")
        except Exception as e:
            tips.append(f"Frame {i+1}: Erro geral - {str(e)}")

    return tips if tips else ["Nenhuma análise foi possível"]

def synthesize_tips_with_gemini(raw_tips, game_name: str):
    """Synthesize raw tips into a polished report using Gemini."""
    try:
        # Nota: O modelo Gemini para síntese pode ser diferente do que você usa no fds.py.
        # 'gemini-2.0-flash' é um bom modelo para essa tarefa.
        model_synth = genai.GenerativeModel('models/gemini-2.0-flash') # Verifique se este modelo está disponível para sua chave!
        
        prompt = (
            f"Você é um assistente de jogos especializado em {game_name}. Recebi as seguintes análises de gameplay de um modelo de visão: \n\n"
            f"{'\n'.join(raw_tips)}\n\n"
            "Sua tarefa é sintetizar essas dicas em um relatório claro, conciso e objetivo. Estruture o relatório em Markdown com: "
            "- Uma introdução resumindo o desempenho geral do jogador. "
            "- Uma lista de dicas específicas, organizadas por categoria (ex.: Posicionamento, Uso de Habilidades, Gestão de Recursos). "
            "- Uma conclusão com recomendações gerais para melhoria. "
            "Use linguagem direta e exemplos práticos. Máximo de 500 palavras."
        )
        response = model_synth.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Erro ao sintetizar dicas com Gemini: {str(e)}"

# --- Função Principal que será chamada pelo Streamlit ---
def run_gameplay_analysis(jogo_alvo: str, gameplay_prompt: str, game_name: str, duration_seconds=30):
    """
    Executa a captura de tela, análise e síntese de gameplay.
    Args:
        jogo_alvo (str): Nome do arquivo executável do jogo (ex: "game.exe").
        gameplay_prompt (str): O prompt gerado pela IA para análise de gameplay.
        game_name (str): O nome do jogo selecionado pelo usuário.
        duration_seconds (int): Duração da gravação em segundos.
    Returns:
        str: O relatório final de análise da gameplay.
    """
    st.write(f"Iniciando gravação de gameplay para {game_name} ({jogo_alvo}). Por favor, jogue por {duration_seconds} segundos...")
    st.write("A gravação será encerrada automaticamente.")

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = f"video_original_{timestamp}.avi"
    compressed_file = f"video_comprimido_{timestamp}.mp4"
    ml_data_file = f"dados_ml_{timestamp}.npy"
    tips_file = f"gameplay_tips_{timestamp}.md" # Não é mais usado para salvar, só para nomeclatura interna

    # --- 1. Gravação do Vídeo ---
    fourcc = cv2.VideoWriter_fourcc(*"XVID")
    video_writer = cv2.VideoWriter(
        output_file,
        fourcc,
        fps,
        (monitor_settings["width"], monitor_settings["height"]),
        isColor=False
    )

    frames_brutos = []
    end_time = time.time() + duration_seconds

    with mss() as sct:
        try:
            while time.time() < end_time:
                # Verificar se o jogo está rodando ANTES de tentar capturar
                if not jogo_esta_rodando(jogo_alvo):
                    # Se o jogo não está rodando, espera um pouco ou avisa
                    st.warning(f"O jogo '{jogo_alvo}' não está em execução. Por favor, inicie o jogo para que a gravação possa começar. Tentando novamente em 5 segundos...")
                    time.sleep(5)
                    continue # Volta para o loop para verificar novamente

                frame = capturar_tela(sct, monitor_settings)
                if frame is not None:
                    try:
                        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
                        video_writer.write(gray_frame)
                        frames_brutos.append(gray_frame)
                    except Exception as e:
                        print(f"❌ Erro no processamento do frame: {str(e)}")
                        #st.error(f"Erro no processamento do frame: {str(e)}")
                        continue
                time.sleep(1/fps) # Controla o FPS
            print("\nGravação encerrada.")
        except Exception as e:
            print(f"❌ Erro durante a gravação: {str(e)}")
            return f"Erro durante a gravação: {str(e)}"
        finally:
            video_writer.release()
            cv2.destroyAllWindows()

    # --- 2. Verificação dos Dados ---
    if not frames_brutos:
        print("❌ Nenhum frame válido foi capturado. Abortando análise.")
        return "❌ Nenhum frame válido foi capturado. Verifique se o jogo estava aberto e visível durante a gravação."

    # --- 3. Compressão do Vídeo (Opcional, pode ser removido se não for usar o arquivo) ---
    # Manter para o caso de você querer salvar o vídeo comprimido
    if os.path.exists(output_file):
        try:
            # st.info(f"Comprimindo vídeo para {compressed_file}...")
            subprocess.run([
                "ffmpeg",
                "-i", output_file,
                "-crf", "28",
                "-preset", "ultrafast",
                compressed_file
            ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) # Captura saída para evitar poluir terminal
            print(f"✅ Vídeo comprimido: {compressed_file}")
            # st.success("Vídeo comprimido com sucesso!")
        except FileNotFoundError:
            print("❌ FFmpeg não encontrado. Certifique-se de que está instalado e no PATH.")
            # st.error("FFmpeg não encontrado. Não foi possível comprimir o vídeo.")
        except subprocess.CalledProcessError as e:
            print(f"❌ Erro na compressão (FFmpeg): {e.stderr.decode()}")
            # st.error(f"Erro na compressão do vídeo: {e.stderr.decode()}")
        except Exception as e:
            print(f"❌ Falha na compressão geral: {str(e)}")
            # st.error(f"Falha na compressão do vídeo: {str(e)}")
    # Remova o arquivo original grande após a compressão
    if os.path.exists(output_file):
        os.remove(output_file)

    # --- 4. Pré-Processamento para ML (Opcional, se você for usar os dados em outro lugar) ---
    try:
        frames_ml = np.array([cv2.resize(f, (64, 64))/255.0 for f in frames_brutos])
        np.save(ml_data_file, frames_ml)
        print(f"✅ Dados para ML salvos em: {ml_data_file}")
    except Exception as e:
        print(f"❌ Falha no pré-processamento de dados para ML: {str(e)}")
        # st.error(f"Falha no pré-processamento de dados para ML: {str(e)}")

    # --- 5. Análise de Gameplay ---
    print("Iniciando análise de gameplay com Llama (OpenRouter)...")
    # st.info("Analisando frames com a IA (isso pode levar alguns minutos)...")
    raw_tips = analyze_gameplay_with_llama(frames_brutos, gameplay_prompt, sample_size=5)
    
    if not raw_tips or raw_tips[0].startswith("Erro"):
        print(f"❌ Erro na análise com Llama: {raw_tips[0] if raw_tips else 'N/A'}")
        return f"❌ Erro na análise com Llama. Por favor, tente novamente. Detalhes: {raw_tips[0] if raw_tips else 'N/A'}"


    print("Sintetizando dicas com Gemini...")
    # st.info("Sintetizando as dicas para um relatório final...")
    final_report = synthesize_tips_with_gemini(raw_tips, game_name)

    if not final_report or final_report.startswith("Erro"):
        print(f"❌ Erro na síntese com Gemini: {final_report}")
        return f"❌ Erro na síntese com Gemini. Por favor, tente novamente. Detalhes: {final_report}"

    # Limpeza de arquivos temporários (opcional, pode ser ajustado)
    if os.path.exists(compressed_file):
        os.remove(compressed_file)
    if os.path.exists(ml_data_file):
        os.remove(ml_data_file)

    return final_report

# Este bloco só será executado se gameplay_analyzer.py for executado diretamente,
# não quando importado pelo fds.py.
if __name__ == "__main__":
    # Exemplo de como você chamaria se fosse testar diretamente:
    # (Comente ou remova as linhas abaixo quando integrar ao Streamlit)
    print("Este script é destinado a ser importado pelo seu aplicativo Streamlit.")
    print("Para testá-lo, você precisaria fornecer um jogo_alvo_exe e um gameplay_prompt.")
    # Exemplo:
    # test_game_exe = "valorant.exe"
    # test_game_name = "Valorant"
    # test_prompt = "Você é um especialista em Valorant. Analise este frame de gameplay..."
    # report = run_gameplay_analysis(test_game_exe, test_prompt, test_game_name, duration_seconds=10)
    # print("\n--- Relatório de Teste ---")
    # print(report)