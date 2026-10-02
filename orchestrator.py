import os
import re
import io
import time
import base64
# pyrefly: ignore [missing-import]
from PIL import Image
import anthropic
from prompts import GENERATOR_SYSTEM_PROMPT, QC_SYSTEM_PROMPT

# Конфігурація API ключів
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

def retry_api_call(func, max_retries=3, delay=10):
    """Повторює API виклик при помилках."""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            error_str = str(e)
            if attempt < max_retries - 1:
                print(f"[RETRY] Спроба {attempt+1}/{max_retries} не вдалась: {error_str}. Чекаю {delay} сек...")
                time.sleep(delay)
            else:
                raise

def get_base64_encoded_image(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode('utf-8')

def call_generator_agent(reference_image_path, complexity_level, patch_prompt=None):
    print(f"\n[Generator Agent] Запуск генерації... (Складність: {complexity_level})")
    if patch_prompt:
        print(f"[Generator Agent] Отримано правки від QC:\n{patch_prompt}")
        
    if not client:
        print("[Generator ERROR] ANTHROPIC_API_KEY не знайдено.")
        return "temp_generated_stencil.png", "Помилка: API ключ відсутній"

    try:
        print("[Generator Agent] Аналіз референсу (Claude 3.5 Sonnet)...")
        base64_data = get_base64_encoded_image(reference_image_path)
        mime_type = 'image/png' if reference_image_path.lower().endswith('.png') else 'image/jpeg'
        
        gen_prompt_text = f"Складність: LEVEL {complexity_level}.\n"
        if patch_prompt:
            gen_prompt_text += f"УВАГА, ВИПРАВЛЕННЯ:\n{patch_prompt}\nВрахуй їх при генерації.\n"
        gen_prompt_text += "Згенеруй детальну текстову інструкцію англійською мовою (IMAGE_PROMPT) для Stable Diffusion, щоб намалювати цей трафарет (тільки чорні лінії на білому фоні, без заливок). Також напиши РЕЗЮМЕ за шаблоном."
        
        def make_call():
            return client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1000,
                system=GENERATOR_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": mime_type,
                                    "data": base64_data,
                                }
                            },
                            {
                                "type": "text",
                                "text": gen_prompt_text
                            }
                        ]
                    }
                ]
            )

        response = retry_api_call(make_call)
        text_response = response.content[0].text
        
        # Парсимо відповідь
        image_prompt_match = re.search(r"IMAGE_PROMPT:\s*(.*?)(?:\nРЕЗЮМЕ|\Z)", text_response, re.DOTALL | re.IGNORECASE)
        image_prompt = image_prompt_match.group(1).strip() if image_prompt_match else f"A stencil coloring template of the subject, simple black outlines on pure white background, strictly no black fills, level {complexity_level} complexity, clean vector style lines."
        
        summary_match = re.search(r"(LEVEL:.*)", text_response, re.DOTALL)
        summary = summary_match.group(1).strip() if summary_match else text_response
        
        # 2. Генерація зображення через відкрите безкоштовне API (Stable Diffusion)
        print("[Generator Agent] Генерація PNG через Pollinations.ai (Stable Diffusion)...")
        import urllib.request
        import urllib.parse
        
        sd_prompt = f"pure white background, simple thin black line art, coloring book page, minimalist stencil, vector style, strict no shading, no gray, only black outlines. {image_prompt}"
        encoded_prompt = urllib.parse.quote(sd_prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&seed={int(time.time())}"
        
        generated_path = f"generated_stencil_lvl_{complexity_level}.png"
        
        req = urllib.request.Request(url, headers={'User-Agent': 'Colorit-Bot'})
        with urllib.request.urlopen(req) as img_response, open(generated_path, 'wb') as out_file:
            data = img_response.read()
            out_file.write(data)
            
        print("[Generator Agent] Зображення успішно згенеровано та збережено!")
        return generated_path, summary

    except Exception as e:
        error_msg = f"Помилка API при генерації: {e}"
        print(f"[Generator ERROR] {error_msg}")
        raise Exception(error_msg)

def call_qc_agent(image_path):
    print(f"\n[QC Agent] Аналіз згенерованого трафарету ({image_path})...")
    
    if not client:
        print("[QC ERROR] ANTHROPIC_API_KEY не знайдено.")
        return "STATUS: FAIL\n<PATCH>Помилка: API ключ відсутній</PATCH>"

    try:
        base64_data = get_base64_encoded_image(image_path)
        mime_type = 'image/png' if image_path.lower().endswith('.png') else 'image/jpeg'
        
        def make_qc_call():
            return client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1000,
                system=QC_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": mime_type,
                                    "data": base64_data,
                                }
                            },
                            {
                                "type": "text",
                                "text": "Проаналізуй цей трафарет. Відповідай строго за шаблоном."
                            }
                        ]
                    }
                ]
            )
            
        print("[QC Agent] Очікування відповіді від моделі Claude 3.5 Sonnet...")
        response = retry_api_call(make_qc_call)
        return response.content[0].text
    except Exception as e:
        print(f"[QC ERROR] Сталася помилка при виклику Anthropic API: {e}")
        return "STATUS: FAIL\n<PATCH>Помилка API. Спробуйте ще раз.</PATCH>"

def run_stencil_automation(reference_image_path, complexity_level):
    MAX_ITERATIONS = 3
    current_patch = None
    
    print(f"Початок конвеєра Colorit Stencil Automation. Ліміт ітерацій: {MAX_ITERATIONS}")
    print(f"Референс: {reference_image_path}, Складність: {complexity_level}")
    
    for i in range(1, MAX_ITERATIONS + 1):
        print(f"\n{'='*50}")
        print(f" ІТЕРАЦІЯ {i} / {MAX_ITERATIONS} ")
        print(f"{'='*50}")
        
        # 1. Генерація
        gen_image_path, gen_summary = call_generator_agent(
            reference_image_path, 
            complexity_level, 
            patch_prompt=current_patch
        )
        print(f"\n[Generator Agent] Резюме:\n{gen_summary}")
        
        # Пауза перед QC аналізом
        time.sleep(5)
        
        # 2. Аналіз QC
        qc_response = call_qc_agent(gen_image_path)
        print(f"\n[QC Agent] Відповідь:\n{qc_response}")
        
        # Пауза після QC перед наступною ітерацією
        time.sleep(5)
        
        # 3. Перевірка статусу
        if "STATUS: PASS" in qc_response:
            print("\n[SUCCESS] QC Agent підтвердив якість (STATUS: PASS)!")
            final_path = f"final_stencil_{complexity_level}.png"
            # Зберігаємо фінальний результат
            if os.path.exists(final_path):
                os.remove(final_path)
            os.rename(gen_image_path, final_path)
            print(f"✅ Фінальний трафарет збережено: {final_path}")
            return final_path
            
        elif "STATUS: FAIL" in qc_response:
            print("\n[FAIL] QC Agent знайшов помилки (STATUS: FAIL).")
            
            # Витягуємо текст правок за допомогою регулярних виразів
            patch_match = re.search(r"<PATCH>(.*?)</PATCH>", qc_response, re.DOTALL)
            
            if patch_match:
                current_patch = patch_match.group(1).strip()
                print(f"[QC Patch Extracted]:\n{current_patch}")
            else:
                print("[WARNING] Не знайдено тегів <PATCH> у відповіді QC. Використовую всю відповідь як правку.")
                current_patch = qc_response
                
            if i == MAX_ITERATIONS:
                print(f"\n[STOP] Досягнуто ліміт ітерацій ({MAX_ITERATIONS}). Пайплайн завершено без PASS.")
                return gen_image_path
            
            # Пауза між ітераціями для уникнення rate limiting
            print(f"\n[PAUSE] Пауза 10 сек перед наступною ітерацією...")
            time.sleep(10)
        else:
            print("\n[ERROR] Не вдалося розпізнати статус у відповіді QC. Зупинка.")
            return None
            
    return None

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Colorit Stencil Automation (Actor-Critic)")
    parser.add_argument("image_path", help="Шлях до референсного зображення (наприклад, image.jpg)")
    parser.add_argument("--level", choices=["S", "M", "H"], default="M", help="Рівень складності трафарету (S, M, H)")
    
    args = parser.parse_args()

    if not os.path.exists(args.image_path):
        print(f"[Помилка] Файл {args.image_path} не знайдено!")
        sys.exit(1)
        
    run_stencil_automation(args.image_path, complexity_level=args.level)
