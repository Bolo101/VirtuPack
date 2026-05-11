import logging
import sys
import os
from datetime import datetime
from typing import List
import textwrap


# Définir le chemin du fichier de log
log_file = "/var/log/disk2qcow2.log"


# Suivi de session - capturer tous les logs pendant la session en cours
_session_logs = []
_session_active = False

class SessionCapturingHandler(logging.Handler):
    """Gestionnaire personnalisé pour capturer les logs de session"""
    def emit(self, record):
        global _session_logs, _session_active
        if _session_active:
            # Formater le message de la même manière que le gestionnaire de fichier
            timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')
            formatted_message = f"[{timestamp}] {record.levelname}: {record.getMessage()}"
            _session_logs.append(formatted_message)


# Configurer la journalisation avec un format de base
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# Ajouter le gestionnaire de capture de session
session_handler = SessionCapturingHandler()
logger.addHandler(session_handler)

try:
    log_handler = logging.FileHandler(log_file)
    log_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(message)s')
    log_handler.setFormatter(formatter)
    logger.addHandler(log_handler)
except PermissionError:
    print("Erreur : permission refusée. Veuillez exécuter le script avec sudo.", file=sys.stderr)
    sys.exit(1)  # Quitter le script pour imposer l'utilisation de sudo
except FileNotFoundError:
    print(f"Erreur : le répertoire de logs n'existe pas : {os.path.dirname(log_file)}", file=sys.stderr)
    sys.exit(1)
except OSError as e:
    print(f"Erreur : impossible de créer le gestionnaire de logs : {e}", file=sys.stderr)
    sys.exit(1)


def log_info(message: str) -> None:
    """Journaliser une information générale à la fois dans la console et dans le fichier de log."""
    logger.info(message)

def log_error(message: str) -> None:
    """Journaliser un message d'erreur à la fois dans la console et dans le fichier de log."""
    logger.error(message)

def log_warning(message: str) -> None:
    """Journaliser un message d'avertissement à la fois dans la console et dans le fichier de log."""
    logger.warning(message)


def session_start() -> None:
    """Journaliser le début de session avec un séparateur clair et démarrer la capture des logs de session"""
    global _session_logs, _session_active
    
    # Effacer les logs de la session précédente et commencer la capture
    _session_logs = []
    _session_active = True
    
    separator = "=" * 80
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        with open(log_file, "a") as f:
            f.write(f"\n{separator}\n")
            f.write(f"SESSION START: {timestamp}\n")
            f.write(f"{separator}\n")
    except PermissionError:
        log_error("Permission refusée lors de l'écriture du début de session dans le fichier de log")
        return
    except OSError as e:
        log_error(f"Erreur système lors de l'écriture du début de session : {e}")
        return
    except IOError as e:
        log_error(f"Erreur d'E/S lors de l'écriture du début de session : {e}")
        return
    
    # Ceci sera également capturé dans les logs de session
    log_info(f"Nouvelle session démarrée à {timestamp}")


def session_end() -> None:
    """Journaliser la fin de session avec un séparateur clair et arrêter la capture des logs de session"""
    global _session_active
    
    separator = "=" * 80
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Journaliser la fin de session (cela sera capturé avant l'arrêt)
    log_info(f"Session terminée à {timestamp}")
    
    # Arrêter la capture des logs de session
    _session_active = False
    
    try:
        with open(log_file, "a") as f:
            f.write(f"\n{separator}\n")
            f.write(f"SESSION END: {timestamp}\n")
            f.write(f"{separator}\n\n")
    except PermissionError:
        log_error("Permission refusée lors de l'écriture de la fin de session dans le fichier de log")
    except OSError as e:
        log_error(f"Erreur système lors de l'écriture de la fin de session : {e}")
    except IOError as e:
        log_error(f"Erreur d'E/S lors de l'écriture de la fin de session : {e}")


def log_application_exit(exit_method: str = "Bouton Quitter") -> None:
    """Journaliser la fermeture de l'application et terminer correctement la session."""
    log_info(f"Application fermée par l'utilisateur via {exit_method}")
    session_end()

def get_current_session_logs() -> List[str]:
    """Récupérer tous les logs de la session en cours"""
    global _session_logs
    return _session_logs.copy()

def is_session_active() -> bool:
    """Vérifier si une session de journalisation est actuellement active"""
    global _session_active
    return _session_active

def generate_session_pdf(output_path: str = None) -> str:
    """
    Générer un PDF à partir des logs de la session en cours en utilisant uniquement les bibliothèques intégrées.


    Args:
        output_path (str, optional): Chemin complet du fichier PDF de sortie.
                                     Si None, un chemin par défaut dans /tmp est utilisé.


    Returns:
        str: Chemin du fichier PDF généré


    Raises:
        ValueError: Si aucun log de session n'est disponible
        PermissionError: Si l'écriture dans le répertoire de sortie est impossible
        OSError: Si les opérations sur le système de fichiers échouent
    """
    # Récupérer les logs de la session en cours
    session_logs = get_current_session_logs()

    if not session_logs:
        raise ValueError("Aucun log de session disponible pour générer le PDF")


    if output_path:
        pdf_path = output_path
        output_dir = os.path.dirname(pdf_path)
        if output_dir:
            try:
                os.makedirs(output_dir, exist_ok=True)
            except PermissionError:
                error_msg = f"Permission refusée lors de la création du répertoire : {output_dir}"
                log_error(error_msg)
                raise PermissionError(error_msg)
            except OSError as e:
                error_msg = f"Erreur système lors de la création du répertoire {output_dir} : {str(e)}"
                log_error(error_msg)
                raise OSError(error_msg)
    else:
        output_dir = "/tmp/disk2qcow2_logs"
        try:
            os.makedirs(output_dir, exist_ok=True)
        except PermissionError:
            error_msg = f"Permission refusée lors de la création du répertoire : {output_dir}"
            log_error(error_msg)
            raise PermissionError(error_msg)
        except OSError as e:
            error_msg = f"Erreur système lors de la création du répertoire {output_dir} : {str(e)}"
            log_error(error_msg)
            raise OSError(error_msg)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_filename = f"disk2qcow2_session_{timestamp}.pdf"
        pdf_path = os.path.join(output_dir, pdf_filename)
    
    try:
        # Créer le PDF à l'aide d'une structure PDF basique
        _create_simple_pdf(
            pdf_path,
            "Disk Cloner - Rapport de logs de session",
            session_logs,
            f"Rapport généré : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Nombre total d'entrées de log : {len(session_logs)}"
        )
        
        log_info(f"PDF des logs de session généré avec succès : {pdf_path}")
        return pdf_path
        
    except PermissionError:
        error_msg = f"Permission refusée lors de l'écriture du PDF vers {pdf_path}"
        log_error(error_msg)
        raise
    except OSError as e:
        error_msg = f"Erreur système pendant la génération du PDF : {str(e)}"
        log_error(error_msg)
        raise
    except IOError as e:
        error_msg = f"Erreur d'E/S pendant la génération du PDF : {str(e)}"
        log_error(error_msg)
        raise IOError(error_msg)

def generate_log_file_pdf(output_path: str = None) -> str:
    """
    Générer un PDF à partir du fichier de log complet en utilisant uniquement les bibliothèques intégrées.


    Args:
        output_path (str, optional): Chemin complet du fichier PDF de sortie.
                                     Si None, un chemin par défaut dans /tmp est utilisé.


    Returns:
        str: Chemin du fichier PDF généré


    Raises:
        FileNotFoundError: Si le fichier de log n'existe pas
        PermissionError: Si la lecture du fichier de log ou l'écriture du PDF est impossible
        UnicodeDecodeError: Si le fichier de log a des problèmes d'encodage
        OSError: Si les opérations sur le système de fichiers échouent
    """
    if output_path:
        pdf_path = output_path
        output_dir = os.path.dirname(pdf_path)
        if output_dir:
            try:
                os.makedirs(output_dir, exist_ok=True)
            except PermissionError:
                error_msg = f"Permission refusée lors de la création du répertoire : {output_dir}"
                log_error(error_msg)
                raise PermissionError(error_msg)
            except OSError as e:
                error_msg = f"Erreur système lors de la création du répertoire {output_dir} : {str(e)}"
                log_error(error_msg)
                raise OSError(error_msg)
    else:
        output_dir = "/tmp/disk2qcow2_logs"
        try:
            os.makedirs(output_dir, exist_ok=True)
        except PermissionError:
            error_msg = f"Permission refusée lors de la création du répertoire : {output_dir}"
            log_error(error_msg)
            raise PermissionError(error_msg)
        except OSError as e:
            error_msg = f"Erreur système lors de la création du répertoire {output_dir} : {str(e)}"
            log_error(error_msg)
            raise OSError(error_msg)


        # Générer le nom du fichier avec horodatage
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_filename = f"disk2qcow2_complete_log_{timestamp}.pdf"
        pdf_path = os.path.join(output_dir, pdf_filename)
    
    # Lire le fichier de log
    if not os.path.exists(log_file):
        error_msg = f"Fichier de log introuvable : {log_file}"
        log_error(error_msg)
        raise FileNotFoundError(error_msg)
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            log_lines = [line.strip() for line in f.readlines() if line.strip()]
    except UnicodeDecodeError:
        # Essayer avec un encodage différent si UTF-8 échoue
        try:
            with open(log_file, 'r', encoding='latin-1') as f:
                log_lines = [line.strip() for line in f.readlines() if line.strip()]
        except UnicodeDecodeError as e:
            error_msg = f"Impossible de décoder le fichier de log avec UTF-8 ou latin-1 : {str(e)}"
            log_error(error_msg)
            raise UnicodeDecodeError(e.encoding, e.object, e.start, e.end, error_msg)
    except PermissionError:
        error_msg = f"Permission refusée lors de la lecture du fichier de log : {log_file}"
        log_error(error_msg)
        raise
    except OSError as e:
        error_msg = f"Erreur système lors de la lecture du fichier de log : {str(e)}"
        log_error(error_msg)
        raise
    except IOError as e:
        error_msg = f"Erreur d'E/S lors de la lecture du fichier de log : {str(e)}"
        log_error(error_msg)
        raise IOError(error_msg)
    
    try:
        # Créer le PDF à l'aide d'une structure PDF basique
        _create_simple_pdf(
            pdf_path,
            "Disk Cloner - Rapport complet du fichier de log",
            log_lines,
            f"Rapport généré : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Fichier de log : {log_file}",
            f"Nombre total de lignes de log : {len(log_lines)}"
        )
        
        log_info(f"PDF du fichier de log complet généré avec succès : {pdf_path}")
        return pdf_path
        
    except PermissionError:
        error_msg = f"Permission refusée lors de l'écriture du PDF vers {pdf_path}"
        log_error(error_msg)
        raise
    except OSError as e:
        error_msg = f"Erreur système pendant la génération du PDF : {str(e)}"
        log_error(error_msg)
        raise
    except IOError as e:
        error_msg = f"Erreur d'E/S pendant la génération du PDF : {str(e)}"
        log_error(error_msg)
        raise IOError(error_msg)

def _create_simple_pdf(file_path: str, title: str, content_lines: List[str], *info_lines: str) -> None:
    """
    Créer un fichier PDF simple en utilisant une structure PDF basique sans bibliothèques externes.
    Gère automatiquement plusieurs pages.
    
    Args:
        file_path: Chemin où enregistrer le PDF
        title: Titre du document
        content_lines: Liste des lignes de contenu à inclure
        *info_lines: Lignes d'information supplémentaires à inclure dans l'en-tête
        
    Raises:
        PermissionError: Si l'écriture dans le fichier est impossible
        OSError: Si les opérations sur le système de fichiers échouent
        ValueError: Si les paramètres fournis sont invalides
    """
    if not file_path:
        raise ValueError("Le chemin du fichier ne peut pas être vide")
    if not title:
        raise ValueError("Le titre ne peut pas être vide")
    if not isinstance(content_lines, list):
        raise ValueError("Les lignes de contenu doivent être une liste")
    
    try:
        with open(file_path, 'wb') as f:
            # En-tête PDF
            f.write(b'%PDF-1.4\n')
            
            # Préparer le contenu et calculer le nombre de pages nécessaires
            try:
                pages_content = _prepare_pdf_pages(title, content_lines, *info_lines)
                num_pages = len(pages_content)
            except (ValueError, TypeError) as e:
                raise ValueError(f"Erreur lors de la préparation des pages PDF : {str(e)}")
            
            # Suivre les positions des objets pour la table xref
            object_positions = {}
            
            # Objet 1 : catalogue
            object_positions[1] = f.tell()
            catalog_obj = b'''1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
>>
endobj
'''
            f.write(catalog_obj)
            
            # Objet 2 : pages (parent) - construire les références de page dynamiquement
            object_positions[2] = f.tell()
            page_object_nums = [3 + i * 2 for i in range(num_pages)]  # Objets page : 3, 5, 7, 9, etc.
            page_refs = " ".join([f"{num} 0 R" for num in page_object_nums])
            
            pages_obj = f'''2 0 obj
<<
/Type /Pages
/Kids [{page_refs}]
/Count {num_pages}
>>
endobj
'''.encode('utf-8')
            f.write(pages_obj)
            
            # Créer les objets page et les flux de contenu
            obj_counter = 3
            for page_idx, page_content in enumerate(pages_content):
                content_bytes = page_content.encode('utf-8')
                content_length = len(content_bytes)
                
                # Objet page (numéros impairs : 3, 5, 7, etc.)
                object_positions[obj_counter] = f.tell()
                page_obj = f'''{obj_counter} 0 obj
<<
/Type /Page
/Parent 2 0 R
/MediaBox [0 0 612 792]
/Contents {obj_counter + 1} 0 R
/Resources <<
/Font <<
/F1 {3 + num_pages * 2} 0 R
>>
>>
>>
endobj
'''.encode('utf-8')
                f.write(page_obj)
                obj_counter += 1
                
                # Objet flux de contenu (numéros pairs : 4, 6, 8, etc.)
                object_positions[obj_counter] = f.tell()
                content_obj = f'''{obj_counter} 0 obj
<<
/Length {content_length}
>>
stream
{page_content}
endstream
endobj
'''.encode('utf-8')
                f.write(content_obj)
                obj_counter += 1
            
            # Objet police (dernier objet)
            font_obj_num = obj_counter
            object_positions[font_obj_num] = f.tell()
            font_obj = f'''{font_obj_num} 0 obj
<<
/Type /Font
/Subtype /Type1
/BaseFont /Courier
>>
endobj
'''.encode('utf-8')
            f.write(font_obj)
            
            # Table de références croisées
            xref_start = f.tell()
            total_objects = font_obj_num + 1
            
            f.write(b'xref\n')
            f.write(f'0 {total_objects}\n'.encode())
            f.write(b'0000000000 65535 f \n')  # Objet 0 (toujours libre)
            
            # Écrire les entrées xref pour tous les objets
            for i in range(1, total_objects):
                if i in object_positions:
                    f.write(f'{object_positions[i]:010d} 00000 n \n'.encode())
                else:
                    f.write(b'0000000000 00000 f \n')  # Marquer comme libre si absent
            
            # Bande-annonce
            trailer = f'''trailer
<<
/Size {total_objects}
/Root 1 0 R
>>
startxref
{xref_start}
%%EOF
'''.encode('utf-8')
            f.write(trailer)
            
    except PermissionError:
        raise PermissionError(f"Permission refusée lors de l'écriture dans le fichier : {file_path}")
    except OSError as e:
        raise OSError(f"Erreur système lors de l'écriture du fichier PDF : {str(e)}")
    except IOError as e:
        raise IOError(f"Erreur d'E/S lors de l'écriture du fichier PDF : {str(e)}")
    except UnicodeEncodeError as e:
        raise ValueError(f"Erreur d'encodage Unicode dans le contenu PDF : {str(e)}")


def _prepare_pdf_pages(title: str, content_lines: List[str], *info_lines: str) -> List[str]:
    """
    Préparer le contenu PDF réparti sur plusieurs pages.
    
    Args:
        title: Titre du document
        content_lines: Liste des lignes de contenu
        *info_lines: Lignes d'information supplémentaires
    
    Returns:
        List[str]: Liste des contenus de pages (flux de contenu PDF)
        
    Raises:
        ValueError: Si les paramètres fournis sont invalides
        TypeError: Si les paramètres sont du mauvais type
    """
    if not isinstance(title, str):
        raise TypeError("Le titre doit être une chaîne de caractères")
    if not isinstance(content_lines, list):
        raise TypeError("Les lignes de contenu doivent être une liste")
    
    try:
        pages = []
        lines_per_page = 55  # Nombre conservateur de lignes tenant sur une page
        first_page_content_lines = lines_per_page - 10  # Tenir compte du titre et des infos
        other_page_content_lines = lines_per_page - 4   # Tenir compte de l'en-tête de page
        
        # Envelopper d'abord toutes les lignes de contenu
        wrapped_lines = []
        display_line_number = 1
        
        if not content_lines:
            wrapped_lines = ["Aucun contenu disponible."]
        else:
            for content_line in content_lines:
                try:
                    wrapped_content = _wrap_log_line(content_line, display_line_number)
                    wrapped_lines.extend(wrapped_content)
                    display_line_number += 1
                except (TypeError, ValueError) as e:
                    # Gérer proprement les lignes problématiques
                    wrapped_lines.append(f"{display_line_number:4d}: [Erreur lors du traitement de la ligne : {str(e)}]")
                    display_line_number += 1
        
        # Répartir les lignes enveloppées sur plusieurs pages
        processed_lines = 0
        page_num = 1
        
        while processed_lines < len(wrapped_lines):
            is_first_page = (page_num == 1)
            max_lines_this_page = first_page_content_lines if is_first_page else other_page_content_lines
            
            # Récupérer les lignes pour cette page
            end_line = min(processed_lines + max_lines_this_page, len(wrapped_lines))
            lines_for_this_page = wrapped_lines[processed_lines:end_line]
            
            if lines_for_this_page:
                try:
                    page_content = _create_page_content(title, lines_for_this_page, page_num, is_first_page, *info_lines)
                    pages.append(page_content)
                except (ValueError, TypeError) as e:
                    # Créer une page de secours si la création du contenu échoue
                    fallback_content = f"BT\n/F1 12 Tf\n50 400 Td\n(Erreur lors de la création de la page {page_num} : {_escape_pdf_string(str(e))}) Tj\nET"
                    pages.append(fallback_content)
                
                processed_lines = end_line
                page_num += 1
                
                # Vérification de sécurité pour éviter les boucles infinies
                if page_num > 100:  # Maximum raisonnable
                    break
            else:
                break
        
        # S'assurer qu'il existe au moins une page
        if not pages:
            try:
                fallback_page = _create_page_content(title, ["Aucun contenu disponible."], 1, True, *info_lines)
                pages.append(fallback_page)
            except (ValueError, TypeError):
                # Secours ultime
                pages.append("BT\n/F1 12 Tf\n50 400 Td\n(Erreur : impossible de créer le contenu de la page) Tj\nET")
        
        return pages
        
    except MemoryError:
        raise ValueError("Contenu trop volumineux à traiter - mémoire insuffisante")
    except RecursionError:
        raise ValueError("Structure de contenu trop complexe - limite de récursion dépassée")


def _create_page_content(title: str, content_lines: List[str], page_number: int, is_first_page: bool, *info_lines: str) -> str:
    """
    Créer le flux de contenu PDF pour une seule page.
    
    Args:
        title: Titre du document
        content_lines: Liste des lignes de contenu pour cette page
        page_number: Numéro de la page actuelle
        is_first_page: Indique s'il s'agit de la première page
        *info_lines: Lignes d'information supplémentaires
    
    Returns:
        str: Flux de contenu PDF pour cette page
        
    Raises:
        ValueError: Si les paramètres fournis sont invalides
        TypeError: Si les paramètres sont du mauvais type
    """
    if not isinstance(title, str):
        raise TypeError("Le titre doit être une chaîne de caractères")
    if not isinstance(content_lines, list):
        raise TypeError("Les lignes de contenu doivent être une liste")
    if not isinstance(page_number, int) or page_number < 1:
        raise ValueError("Le numéro de page doit être un entier positif")
    if not isinstance(is_first_page, bool):
        raise TypeError("is_first_page doit être un booléen")
    
    try:
        lines = []
        
        # Démarrer le flux de contenu
        lines.append("BT")  # Début du texte
        lines.append("/F1 8 Tf")  # Définir la police tôt
        
        if is_first_page:
            # Première page : en-tête complet avec titre et infos
            lines.append("50 750 Td")  # Aller à la position du haut
            lines.append("/F1 16 Tf")  # Police plus grande pour le titre
            lines.append(f"({_escape_pdf_string(title)}) Tj")
            
            # Ajouter les lignes d'information
            lines.append("/F1 10 Tf")  # Police plus petite pour les infos
            for info_line in info_lines:
                lines.append("0 -15 Td")  # Descendre de 15 points
                lines.append(f"({_escape_pdf_string(info_line)}) Tj")
            
            lines.append("0 -20 Td")  # Espace supplémentaire avant le contenu
            lines.append("/F1 8 Tf")   # Définir la police du contenu
        else:
            # Pages suivantes : en-tête de page simple
            lines.append("50 750 Td")  # Aller à la position du haut
            lines.append("/F1 12 Tf")  # Police moyenne pour l'en-tête de page
            lines.append(f"({_escape_pdf_string(f'{title} - Page {page_number}')}) Tj")
            lines.append("0 -25 Td")   # Descendre avant le contenu
            lines.append("/F1 8 Tf")   # Définir la police du contenu
        
        # Ajouter les lignes de contenu
        for i, content_line in enumerate(content_lines):
            lines.append("0 -12 Td")  # Descendre de 12 points
            try:
                escaped_line = _escape_pdf_string(content_line)
                lines.append(f"({escaped_line}) Tj")
            except (TypeError, ValueError):
                # Gérer proprement le contenu problématique
                lines.append(f"([Ligne {i+1} : erreur lors du traitement du contenu]) Tj")
        
        # Ajouter le numéro de page en bas (déplacement en position absolue)
        lines.append("50 30 Td")  # Aller en bas à gauche (position absolue)
        lines.append("/F1 8 Tf")  # S'assurer que la police est définie
        lines.append(f"({_escape_pdf_string(f'Page {page_number}')}) Tj")
        
        lines.append("ET")  # Fin du texte
        
        return "\n".join(lines)
        
    except MemoryError:
        # Retourner une page d'erreur minimale en cas de manque de mémoire
        return f"BT\n/F1 12 Tf\n50 400 Td\n(Erreur : page {page_number} - mémoire insuffisante) Tj\nET"


def _wrap_log_line(content_line: str, line_number: int, max_width: int = 75) -> List[str]:
    """
    Découper une ligne de log unique en plusieurs lignes si elle est trop longue.
    
    Args:
        content_line: La ligne de log originale
        line_number: Le numéro de ligne à afficher
        max_width: Nombre maximal de caractères par ligne (en tenant compte du préfixe du numéro de ligne)
    
    Returns:
        List[str]: Liste des lignes découpées avec le formatage approprié
        
    Raises:
        TypeError: Si les paramètres sont du mauvais type
        ValueError: Si les paramètres sont invalides
    """
    if not isinstance(content_line, str):
        raise TypeError("La ligne de contenu doit être une chaîne de caractères")
    if not isinstance(line_number, int) or line_number < 1:
        raise ValueError("Le numéro de ligne doit être un entier positif")
    if not isinstance(max_width, int) or max_width < 10:
        raise ValueError("La largeur maximale doit être un entier >= 10")
    
    try:
        # Calculer la largeur disponible après le préfixe du numéro de ligne
        line_prefix = f"{line_number:4d}: "
        continuation_prefix = "      "  # 6 espaces pour aligner avec le contenu
        available_width = max_width - len(line_prefix)
        
        if available_width < 10:
            # Solution de secours pour les largeurs très faibles
            return [f"{line_number:4d}: {content_line[:10]}..."]
        
        try:
            # Utiliser textwrap pour couper les lignes longues sur les limites des mots
            wrapped_content = textwrap.fill(
                content_line,
                width=available_width,
                break_long_words=True,
                break_on_hyphens=True,
                expand_tabs=True,
                replace_whitespace=False
            )
        except (TypeError, ValueError):
            # Solution de secours avec troncature simple si textwrap échoue
            if len(content_line) > available_width:
                wrapped_content = content_line[:available_width-3] + "..."
            else:
                wrapped_content = content_line
        
        wrapped_lines = wrapped_content.split('\n')
        
        # Formater les lignes avec les préfixes appropriés
        formatted_lines = []
        for i, line in enumerate(wrapped_lines):
            if i == 0:
                # La première ligne reçoit le numéro de ligne
                formatted_lines.append(f"{line_prefix}{line}")
            else:
                # Les lignes suivantes sont indentées pour s'aligner avec le contenu
                formatted_lines.append(f"{continuation_prefix}{line}")
        
        return formatted_lines
        
    except MemoryError:
        # Solution de secours en cas de problème mémoire
        return [f"{line_number:4d}: [Erreur mémoire lors du traitement de la ligne]"]
    except RecursionError:
        # Solution de secours en cas de problème de récursion
        return [f"{line_number:4d}: [Erreur de récursion lors du traitement de la ligne]"]


def _escape_pdf_string(text: str) -> str:
    """
    Échapper les caractères spéciaux dans les chaînes PDF.
    
    Args:
        text: Texte à échapper
    
    Returns:
        str: Texte échappé, sûr pour le PDF
        
    Raises:
        TypeError: Si text n'est pas une chaîne de caractères
    """
    if text is None:
        return ""
    
    try:
        # Convertir en chaîne si ce n'est pas déjà le cas
        text = str(text)
        
        # Remplacer les caractères spéciaux des chaînes PDF
        text = text.replace('\\', '\\\\')  # L'antislash doit être traité en premier
        text = text.replace('(', '\\(')
        text = text.replace(')', '\\)')
        text = text.replace('\r', ' ')
        text = text.replace('\n', ' ')
        text = text.replace('\t', ' ')
        
        # Supprimer ou remplacer les caractères non imprimables
        cleaned_text = ""
        for char in text:
            try:
                char_ord = ord(char)
                if 32 <= char_ord <= 126:
                    cleaned_text += char
                else:
                    cleaned_text += " "  # Remplacer par un espace
            except (TypeError, ValueError):
                cleaned_text += " "  # Remplacer les caractères problématiques par un espace
        
        return cleaned_text
        
    except (TypeError, ValueError, AttributeError):
        return f"[Erreur lors du traitement du texte : {type(text).__name__}]"
    except MemoryError:
        return "[Erreur mémoire lors du traitement du texte]"