import os
import requests
import json
import logging

logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://ollama:11434')
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'phi3:mini')


def check_ollama_available():
    """Check if Ollama is running and accessible"""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return response.status_code == 200
    except:
        return False


def ensure_model_available():
    """Check if the model is available, pull it if not"""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
        if response.status_code == 200:
            models = response.json().get('models', [])
            model_names = [m.get('name', '').split(':')[0] for m in models]
            
            # Check if our model is available
            base_model = OLLAMA_MODEL.split(':')[0]
            if base_model not in model_names and OLLAMA_MODEL not in [m.get('name') for m in models]:
                logger.info(f"Model {OLLAMA_MODEL} not found, pulling...")
                pull_model(OLLAMA_MODEL)
                return True
            return True
    except Exception as e:
        logger.error(f"Error checking model availability: {e}")
    return False


def pull_model(model_name):
    """Pull a model from Ollama"""
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/pull",
            json={"name": model_name},
            timeout=600,  # 10 minute timeout for pulling
            stream=True
        )
        # Stream the response to show progress
        for line in response.iter_lines():
            if line:
                logger.info(f"Pulling {model_name}: {line.decode()}")
        return True
    except Exception as e:
        logger.error(f"Error pulling model {model_name}: {e}")
        return False


def generate_site_metadata(url, existing_categories=None):
    """
    Use Ollama to generate category and description for a site.
    
    Args:
        url: The URL of the site
        existing_categories: List of existing category names to prefer
    
    Returns:
        dict with 'category' and 'description' keys, or None if failed
    """
    if not check_ollama_available():
        logger.warning("Ollama not available, skipping AI metadata generation")
        return None
    
    # Build the prompt
    categories_hint = ""
    if existing_categories:
        categories_hint = f"Existing categories in the system: {', '.join(existing_categories)}. Prefer using one of these if appropriate, or suggest a new one if none fit."
    
    prompt = f"""Analyze this URL and provide metadata for a web archive system.

URL: {url}

{categories_hint}

Respond ONLY with a JSON object in this exact format, no other text:
{{"category": "category name in Italian", "description": "brief description in Italian, max 100 characters"}}

The category should be general (e.g., "Blog personali", "Riviste online", "Documentazione tecnica", "Arte e cultura", "Musica", "Video e streaming").
The description should briefly explain what the site is about.

JSON response:"""

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 150
                }
            },
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            text = result.get('response', '').strip()
            
            # Try to extract JSON from the response
            try:
                # Find JSON in the response
                start = text.find('{')
                end = text.rfind('}') + 1
                if start >= 0 and end > start:
                    json_str = text[start:end]
                    metadata = json.loads(json_str)
                    return {
                        'category': metadata.get('category', '').strip(),
                        'description': metadata.get('description', '').strip()[:200]
                    }
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse AI response as JSON: {text[:200]}")
                
    except Exception as e:
        logger.error(f"Error generating metadata with Ollama: {e}")
    
    return None


def generate_batch_metadata(urls, existing_categories=None):
    """
    Generate metadata for multiple URLs.
    
    Args:
        urls: List of URLs
        existing_categories: List of existing category names
    
    Returns:
        dict mapping URL to metadata dict
    """
    results = {}
    
    for url in urls:
        metadata = generate_site_metadata(url, existing_categories)
        if metadata:
            results[url] = metadata
        else:
            results[url] = {'category': None, 'description': None}
    
    return results
