import os
import re
import io
# pyrefly: ignore [missing-import]
from PIL import Image
from google import genai
from google.genai import types
from prompts import GENERATOR_SYSTEM_PROMPT, QC_SYSTEM_PROMPT

# Конфігурація API ключів
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

def call_generator_agent(reference_image_path, complexity_level, patch_prompt=None):
    """
    Виклик Агента-Генератора. Використовує gemini-2.0-flash для аналізу референсу та генерації 
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
        uploaded_ref = client.files.upload(file=reference_image_path)
        
        gen_prompt_text = f"Складність: LEVEL {complexity_level}.\n"
        if patch_prompt:
            gen_prompt_text += f"УВАГА, ВИПРАВЛЕННЯ:\n{patch_prompt}\nВрахуй їх при генерації.\n"
        gen_prompt_text += "Згенеруй детальну текстову інструкцію англійською мовою (IMAGE_PROMPT) для Imagen 3, щоб намалювати цей трафарет (тільки чорні лінії на білому фоні, без заливок). Також напиши РЕЗЮМЕ за шаблоном."
        
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=[
                gen_prompt_text,
                uploaded_ref
            ],
            config=types.GenerateContentConfig(
                system_instruction=GENERATOR_SYSTEM_PROMPT,
                temperature=0.2
            )
        )
        
        # Парсимо відповідь
        text_response = response.text
        # Спрощена логіка: якщо є IMAGE_PROMPT, витягуємо його
        image_prompt_match = re.search(r"IMAGE_PROMPT:\s*(.*?)(?:\nРЕЗЮМЕ|\Z)", text_response, re.DOTALL | re.IGNORECASE)
        image_prompt = image_prompt_match.group(1).strip() if image_prompt_match else f"A stencil coloring template of the subject, simple black outlines on pure white background, strictly no black fills, level {complexity_level} complexity, clean vector style lines."
        
        summary_match = re.search(r"(LEVEL:.*)", text_response, re.DOTALL)
        summary = summary_match.group(1).strip() if summary_match else text_response
        
        # 2. Генерація зображення через Imagen 3
        print("[Generator Agent] Генерація PNG через Imagen 3...")
        result = client.models.generate_images(
            model='imagen-3.0-generate-002',
            prompt=image_prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                output_mime_type="image/png",
                aspect_ratio="1:1"
            )
        )
        
        generated_path = f"generated_stencil_lvl_{complexity_level}.png"
        for generated_image in result.generated_images:
            image = Image.open(io.BytesIO(generated_image.image.image_bytes))
            image.save(generated_path)
            break
            
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
        # Завантаження файлу в Gemini API
        print("[QC Agent] Завантаження зображення...")
        uploaded_file = client.files.upload(file=image_path)
        
        print("[QC Agent] Очікування відповіді від моделі gemini-2.0-flash...")
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=[
                "Проаналізуй цей трафарет. Відповідай строго за шаблоном.",
                uploaded_file
            ],
            config=types.GenerateContentConfig(
                system_instruction=QC_SYSTEM_PROMPT,
                temperature=0.1 # Низька температура для більш стабільного аналізу
            )
        )
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
        
        # 2. Аналіз QC
        qc_response = call_qc_agent(gen_image_path)
        print(f"\n[QC Agent] Відповідь:\n{qc_response}")
        
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
                return gen_image_path # Повертаємо хоча б останній результат
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
