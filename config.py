import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

class Config:
    """Конфигурация бота"""
    
    # Токен Discord бота
    DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
    
    # Префикс команд
    COMMAND_PREFIX = os.getenv('COMMAND_PREFIX', '!')
    
    # Файл конфигурации каналов
    CHANNELS_CONFIG_FILE = os.getenv('CHANNELS_CONFIG_FILE', 'channels_config.json')
    
    # Максимальный размер файла для пересылки (в байтах)
    MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', '8388608'))  # 8MB по умолчанию
    
    # Цвета для embed'ов
    EMBED_COLOR_DEFAULT = int(os.getenv('EMBED_COLOR_DEFAULT', '0x393a41'), 16)
    EMBED_COLOR_SUCCESS = int(os.getenv('EMBED_COLOR_SUCCESS', '0x393a41'), 16)
    EMBED_COLOR_INFO = int(os.getenv('EMBED_COLOR_INFO', '0x393a41'), 16)
    EMBED_COLOR_WARNING = int(os.getenv('EMBED_COLOR_WARNING', '0x393a41'), 16)
    EMBED_COLOR_ERROR = int(os.getenv('EMBED_COLOR_ERROR', '0x393a41'), 16)
    EMBED_COLOR_MESSAGE = int(os.getenv('EMBED_COLOR_MESSAGE', '0x393a41'), 16)
    
    # Настройки логирования
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.getenv('LOG_FILE', 'bot.log')
    
    # Максимальная длина сообщения
    MAX_MESSAGE_LENGTH = int(os.getenv('MAX_MESSAGE_LENGTH', '2000'))
    
    # Включить/выключить логирование сообщений
    LOG_MESSAGES = os.getenv('LOG_MESSAGES', 'false').lower() == 'true'
    
    # Автоматическое удаление недоступных каналов при запуске
    AUTO_CLEANUP_CHANNELS = os.getenv('AUTO_CLEANUP_CHANNELS', 'true').lower() == 'true'
    
    # Настройки автоматической выдачи ролей новым участникам
    AUTO_ROLE_ENABLED = os.getenv('AUTO_ROLE_ENABLED', 'false').lower() == 'true'
    AUTO_ROLE_ID = os.getenv('AUTO_ROLE_ID', '1388951105521586307')  # ID роли для выдачи
    AUTO_ROLE_GUILD_ID = os.getenv('AUTO_ROLE_GUILD_ID', '1387900625324478506')  # ID сервера
    
    # Настройки антиспам системы
    ANTISPAM_ENABLED = os.getenv('ANTISPAM_ENABLED', 'true').lower() == 'true'
    ANTISPAM_MAX_MESSAGES = int(os.getenv('ANTISPAM_MAX_MESSAGES', '5'))  # Максимум сообщений
    ANTISPAM_TIME_WINDOW = int(os.getenv('ANTISPAM_TIME_WINDOW', '10'))  # За период в секундах
    ANTISPAM_MUTE_DURATION = int(os.getenv('ANTISPAM_MUTE_DURATION', '60'))  # Время мута в секундах
    ANTISPAM_LOG_CHANNEL_ID = 1388981755263844576  # ID канала для уведомлений о спаме
    
    # Настройки анти-рейд защиты
    RAID_PROTECTION_ENABLED = os.getenv('RAID_PROTECTION_ENABLED', 'true').lower() == 'true'
    RAID_PROTECTION_BLOCK_MASS_MENTIONS = os.getenv('RAID_PROTECTION_BLOCK_MASS_MENTIONS', 'true').lower() == 'true'  # Блокировать @everyone/@here
    RAID_PROTECTION_BLOCK_DISCORD_INVITES = os.getenv('RAID_PROTECTION_BLOCK_DISCORD_INVITES', 'true').lower() == 'true'  # Блокировать Discord инвайты
    
    # Настройки системы уведомлений о подключениях/отключениях
    CONNECTION_NOTIFICATIONS_ENABLED = os.getenv('CONNECTION_NOTIFICATIONS_ENABLED', 'true').lower() == 'true'
    CONNECTION_NOTIFICATIONS_CHANNEL_ID = int(os.getenv('CONNECTION_NOTIFICATIONS_CHANNEL_ID', '1388981755263844576'))  # ID канала для уведомлений
    CONNECTION_NOTIFICATIONS_GUILD_ID = os.getenv('CONNECTION_NOTIFICATIONS_GUILD_ID', '1387900625324478506')  # ID сервера для отслеживания
    
    # Настройки системы чёрного списка
    BLACKLIST_ENABLED = os.getenv('BLACKLIST_ENABLED', 'true').lower() == 'true'
    BLACKLIST_MODERATOR_ROLE_ID = int(os.getenv('BLACKLIST_MODERATOR_ROLE_ID', '1388985886099902504'))  # ID роли модератора
    BLACKLIST_BAN_CHANNEL_ID = int(os.getenv('BLACKLIST_BAN_CHANNEL_ID', '1388985623268032645'))  # ID канала для блокировки
    BLACKLIST_UNBAN_CHANNEL_ID = int(os.getenv('BLACKLIST_UNBAN_CHANNEL_ID', '1388985666821423134'))  # ID канала для разблокировки
    BLACKLIST_FILE = os.getenv('BLACKLIST_FILE', 'blacklist.json')  # Файл для хранения чёрного списка
    
    # Система уровней
    LEVELS_ENABLED = os.getenv('LEVELS_ENABLED', 'true').lower() == 'true'
    LEVELS_FILE = os.getenv('LEVELS_FILE', 'levels.json')
    LEVELS_XP_MIN = int(os.getenv('LEVELS_XP_MIN', '5'))
    LEVELS_XP_MAX = int(os.getenv('LEVELS_XP_MAX', '15'))
    LEVELS_COOLDOWN_SECONDS = int(os.getenv('LEVELS_COOLDOWN_SECONDS', '60'))
    LEVELS_DAILY_BONUS = int(os.getenv('LEVELS_DAILY_BONUS', '20'))
    LEVELS_FIRST_MESSAGE_BONUS = int(os.getenv('LEVELS_FIRST_MESSAGE_BONUS', '10'))
    
    @classmethod
    def validate(cls):
        """Проверяет корректность конфигурации"""
        errors = []
        
        if not cls.DISCORD_TOKEN:
            errors.append("DISCORD_TOKEN не установлен")
        
        if cls.MAX_FILE_SIZE <= 0:
            errors.append("MAX_FILE_SIZE должен быть положительным числом")
        
        if cls.MAX_MESSAGE_LENGTH <= 0:
            errors.append("MAX_MESSAGE_LENGTH должен быть положительным числом")
        
        return errors

# Проверяем конфигурацию при импорте
config_errors = Config.validate()
if config_errors:
    print("❌ Ошибки конфигурации:")
    for error in config_errors:
        print(f"  - {error}")
    print("\nПроверьте файл .env или переменные окружения")
    exit(1)