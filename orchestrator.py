import os
import re
import io
import time
# pyrefly: ignore [missing-import]
from PIL import Image
from google import genai
from google.genai import types
from prompts import GENERATOR_SYSTEM_PROMPT, QC_SYSTEM_PROMPT

# Конфігурація API ключів
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

def retry_api_call(func, max_retries=5, delay=20):
    """Повторює API виклик при 503/429 помилках."""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            error_str = str(e)
            if ('503' in error_str or '429' in error_str or 'UNAVAILABLE' in error_str) and attempt < max_retries - 1:
                print(f"[RETRY] Спроба {attempt+1}/{max_retries} не вдалась (сервер перевантажений). Чекаю {delay} сек...")
                time.sleep(delay)
            else:
                raise


def call_generator_agent(reference_image_path, complexity_level, patch_prompt=None):
    """
    Виклик Агента-Генератора. Використовує gemini-2.5-flash для аналізу референсу та генерації 
    текстового промпту, і imagen-3.0-generate-002 для відмальовки трафарету.
    """
    print(f"\n[Generator Agent] Запуск генерації... (Складність: {complexity_level})")
    if patch_prompt:
        print(f"[Generator Agent] Отримано правки від QC:\n{patch_prompt}")
        
    if not client:
        print("[Generator ERROR] GEMINI_API_KEY не знайдено.")
        return "temp_generated_stencil.png", "Помилка: API ключ відсутній"

    try:
        # 1. Аналіз референсу та підготовка промпту для Imagen
        print("[Generator Agent] Аналіз референсу...")
        with open(reference_image_path, 'rb') as f:
            image_bytes = f.read()
        
        # Визначаємо MIME тип
        mime_type = 'image/jpeg'
        if reference_image_path.lower().endswith('.png'):
            mime_type = 'image/png'
        
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        
        gen_prompt_text = f"Складність: LEVEL {complexity_level}.\n"
        if patch_prompt:
            gen_prompt_text += f"УВАГА, ВИПРАВЛЕННЯ:\n{patch_prompt}\nВрахуй їх при генерації.\n"
        gen_prompt_text += "Згенеруй детальну текстову інструкцію англійською мовою (IMAGE_PROMPT) для Imagen 3, щоб намалювати цей трафарет (тільки чорні лінії на білому фоні, без заливок). Також напиши РЕЗЮМЕ за шаблоном."
        
        response = retry_api_call(lambda: client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                gen_prompt_text,
                image_part
            ],
            config=types.GenerateContentConfig(
                system_instruction=GENERATOR_SYSTEM_PROMPT,
                temperature=0.2
            )
        ))
        
        # Пауза між API викликами щоб не перевантажити сервер
        time.sleep(5)
        
        # Парсимо відповідь
        text_response = response.text
        # Спрощена логіка: якщо є IMAGE_PROMPT, витягуємо його
        image_prompt_match = re.search(r"IMAGE_PROMPT:\s*(.*?)(?:\nРЕЗЮМЕ|\Z)", text_response, re.DOTALL | re.IGNORECASE)
        image_prompt = image_prompt_match.group(1).strip() if image_prompt_match else f"A stencil coloring template of the subject, simple black outlines on pure white background, strictly no black fills, level {complexity_level} complexity, clean vector style lines."
        
        summary_match = re.search(r"(LEVEL:.*)", text_response, re.DOTALL)
        summary = summary_match.group(1).strip() if summary_match else text_response
        
        # 2. Генерація зображення через відкрите безкоштовне API (Stable Diffusion)
        print("[Generator Agent] Генерація PNG через Pollinations.ai (Stable Diffusion)...")
        import urllib.request
        import urllib.parse
        
        # Модифікуємо промпт, щоб точно отримати трафарет від відкритої моделі
        sd_prompt = f"pure white background, simple thin black line art, coloring book page, minimalist stencil, vector style, strict no shading, no gray, only black outlines. {image_prompt}"
        encoded_prompt = urllib.parse.quote(sd_prompt)
        
        # Додаємо seed для унікальності та nologo щоб прибрати водяний знак
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&seed={int(time.time())}"
        
        generated_path = f"generated_stencil_lvl_{complexity_level}.png"
        
        # Завантажуємо зображення
        req = urllib.request.Request(url, headers={'User-Agent': 'Colorit-Bot'})
        with urllib.request.urlopen(req) as response, open(generated_path, 'wb') as out_file:
            data = response.read()
            out_file.write(data)
            
        print("[Generator Agent] Зображення успішно згенеровано та збережено!")
        return generated_path, summary

    except Exception as e:
        error_msg = f"Помилка API при генерації: {e}"
        print(f"[Generator ERROR] {error_msg}")
        raise Exception(error_msg)

def call_qc_agent(image_path):
    """
    Виклик Агента-Критика (Gemini Vision) для аналізу трафарету.
    """
    print(f"\n[QC Agent] Аналіз згенерованого трафарету ({image_path})...")
    
    if not client:
        print("[QC ERROR] GEMINI_API_KEY не знайдено в змінних середовища.")
        print("[QC Agent] Повернення тестової відповіді для демонстрації.")
        return "STATUS: FAIL\nVIOLATIONS: F1: Плаваючі острови.\n<PATCH>Виправ острови в області ока.</PATCH>"

    try:
        # Завантаження файлу як байтів
        print("[QC Agent] Завантаження зображення...")
        with open(image_path, 'rb') as f:
            image_bytes = f.read()
        
        mime_type = 'image/png' if image_path.lower().endswith('.png') else 'image/jpeg'
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        
        print("[QC Agent] Очікування відповіді від моделі gemini-2.5-flash...")
        response = retry_api_call(lambda: client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                "Проаналізуй цей трафарет. Відповідай строго за шаблоном.",
                image_part
            ],
            config=types.GenerateContentConfig(
                system_instruction=QC_SYSTEM_PROMPT,
                temperature=0.1
            )
        ))
        return response.text
    except Exception as e:
        print(f"[QC ERROR] Сталася помилка при виклику Gemini API: {e}")
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
