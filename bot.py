import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import io
import logging
import re
import random
from datetime import datetime, timedelta
from config import Config
from flask import Flask, jsonify
from flask_cors import CORS
import threading
import time

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(Config.LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('DiscordBot')

# Настройки бота
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True  # Необходимо для отслеживания присоединения участников

bot = commands.Bot(command_prefix=Config.COMMAND_PREFIX, intents=intents)

# Загрузка конфигурации каналов
def load_channels_config():
    """Загружает конфигурацию связанных каналов"""
    if os.path.exists(Config.CHANNELS_CONFIG_FILE):
        try:
            with open(Config.CHANNELS_CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # Проверяем формат данных и конвертируем старый формат в новый
                if data and isinstance(list(data.values())[0], str):
                    # Старый формат: {channel_id: network_name}
                    logger.info("Конвертируем старый формат конфигурации в новый")
                    new_data = {}
                    for channel_id, network_name in data.items():
                        new_data[channel_id] = {
                            'network': network_name,
                            'guild_id': None,
                            'guild_name': 'Неизвестно',
                            'channel_name': 'Неизвестно',
                            'linked_at': datetime.utcnow().isoformat(),
                            'linked_by': 'Неизвестно'
                        }
                    save_channels_config(new_data)
                    return new_data
                
                logger.info(f"Загружена конфигурация каналов: {len(data)} каналов")
                return data
        except Exception as e:
            logger.error(f"Ошибка при загрузке конфигурации каналов: {e}")
    return {}

# Сохранение конфигурации каналов
def save_channels_config(config):
    """Сохраняет конфигурацию связанных каналов"""
    try:
        with open(Config.CHANNELS_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        logger.info(f"Конфигурация каналов сохранена: {len(config)} каналов")
    except Exception as e:
        logger.error(f"Ошибка при сохранении конфигурации каналов: {e}")

# Для совместимости со старым кодом
def load_config():
    """Загружает конфигурацию связанных каналов (устаревшая функция)"""
    return load_channels_config()

def save_config():
    """Сохраняет конфигурацию связанных каналов (устаревшая функция)"""
    save_channels_config(linked_channels)

# Глобальная переменная для хранения связанных каналов
linked_channels = load_channels_config()

# Антиспам система - словарь для отслеживания времени последних сообщений пользователей
# Структура: {user_id: [timestamp1, timestamp2, ...]} - последние сообщения за период
user_message_times = {}

# Словарь для отслеживания замученных пользователей
# Структура: {user_id: timestamp_when_mute_ends}
muted_users = {}

# Система чёрного списка
def load_blacklist():
    """Загружает чёрный список из файла"""
    if os.path.exists(Config.BLACKLIST_FILE):
        try:
            with open(Config.BLACKLIST_FILE, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except (json.JSONDecodeError, FileNotFoundError):
            logger.warning(f"Не удалось загрузить чёрный список из {Config.BLACKLIST_FILE}")
            return set()
    return set()

def save_blacklist(blacklist):
    """Сохраняет чёрный список в файл"""
    try:
        with open(Config.BLACKLIST_FILE, 'w', encoding='utf-8') as f:
            json.dump(list(blacklist), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка при сохранении чёрного списка: {e}")

def add_to_blacklist(user_id):
    """Добавляет пользователя в чёрный список"""
    blacklist = load_blacklist()
    blacklist.add(str(user_id))
    save_blacklist(blacklist)
    logger.info(f"Пользователь {user_id} добавлен в чёрный список")
    return True

def remove_from_blacklist(user_id):
    """Удаляет пользователя из чёрного списка"""
    blacklist = load_blacklist()
    user_id_str = str(user_id)
    if user_id_str in blacklist:
        blacklist.remove(user_id_str)
        save_blacklist(blacklist)
        logger.info(f"Пользователь {user_id} удалён из чёрного списка")
        return True
    return False

def is_blacklisted(user_id):
    """Проверяет, находится ли пользователь в чёрном списке"""
    blacklist = load_blacklist()
    return str(user_id) in blacklist

def remove_links_from_text(text):
    """Удаляет ссылки из текста, заменяя их на '(ссылка удалена)'"""
    # Паттерн для поиска URL (http, https, ftp, www)
    url_pattern = r'(?:(?:https?|ftp)://|www\.)(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    
    # Заменяем найденные ссылки на текст
    modified_text = re.sub(url_pattern, '(ссылка удалена)', text)
    
    return modified_text

async def send_violation_report(message, violation_type, original_content=None):
    """Отправляет уведомление о нарушении в канал модерации"""
    moderation_channel_id = 1389343409952522390
    
    try:
        moderation_channel = bot.get_channel(moderation_channel_id)
        if not moderation_channel:
            logger.error(f"Канал модерации {moderation_channel_id} не найден")
            return
        
        # Создаем embed с информацией о нарушении
        embed = discord.Embed(
            title="🚨 Обнаружено нарушение",
            color=0xff0000,
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(
            name="Тип нарушения",
            value=violation_type,
            inline=False
        )
        
        embed.add_field(
            name="Пользователь",
            value=f"{message.author.mention} ({message.author.name}#{message.author.discriminator})\nID: {message.author.id}",
            inline=True
        )
        
        embed.add_field(
            name="Сервер",
            value=f"{message.guild.name}\nID: {message.guild.id}",
            inline=True
        )
        
        embed.add_field(
            name="Канал",
            value=f"#{message.channel.name}\nID: {message.channel.id}",
            inline=True
        )
        
        if original_content:
            embed.add_field(
                name="Оригинальное сообщение",
                value=original_content[:1000] + ("..." if len(original_content) > 1000 else ""),
                inline=False
            )
        
        # Добавляем ссылку на сообщение, если оно не было удалено
        try:
            message_link = f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{message.id}"
            embed.add_field(
                name="Ссылка на сообщение",
                value=f"[Перейти к сообщению]({message_link})",
                inline=False
            )
        except:
            embed.add_field(
                name="Ссылка на сообщение",
                value="Сообщение было удалено",
                inline=False
            )
        
        # Добавляем инвайт на сервер
        try:
            invite = await message.channel.create_invite(
                max_age=86400,  # 24 часа
                max_uses=1,
                reason="Модерация бота - проверка нарушения"
            )
            embed.add_field(
                name="Инвайт на сервер",
                value=f"[Присоединиться к серверу]({invite.url})",
                inline=False
            )
        except Exception as e:
            logger.warning(f"Не удалось создать инвайт для сервера {message.guild.name}: {e}")
            embed.add_field(
                name="Инвайт на сервер",
                value="Не удалось создать инвайт",
                inline=False
            )
        
        await moderation_channel.send(embed=embed)
        logger.info(f"Отправлено уведомление о нарушении: {violation_type} от {message.author.name} на сервере {message.guild.name}")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления о нарушении: {e}")

# Система уровней
levels_data = {}
last_xp_time = {}  # Для отслеживания кулдауна XP

def load_levels():
    """Загружает данные уровней из файла"""
    global levels_data
    try:
        if os.path.exists(Config.LEVELS_FILE):
            with open(Config.LEVELS_FILE, 'r', encoding='utf-8') as f:
                levels_data = json.load(f)
                logger.info(f"Загружены данные уровней для {len(levels_data)} пользователей")
        else:
            levels_data = {}
            logger.info("Файл уровней не найден, создан новый")
    except Exception as e:
        logger.error(f"Ошибка при загрузке уровней: {e}")
        levels_data = {}

def save_levels():
    """Сохраняет данные уровней в файл"""
    try:
        with open(Config.LEVELS_FILE, 'w', encoding='utf-8') as f:
            json.dump(levels_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка при сохранении уровней: {e}")

def calculate_level(xp):
    """Вычисляет уровень на основе XP"""
    # Формула: level = floor(sqrt(xp / 100))
    return int((xp / 100) ** 0.5)

def calculate_xp_for_level(level):
    """Вычисляет необходимое XP для достижения уровня"""
    return level * level * 100

def add_xp(user_id, xp_amount):
    """Добавляет XP пользователю и возвращает новый уровень"""
    user_id_str = str(user_id)
    
    if user_id_str not in levels_data:
        levels_data[user_id_str] = {
            'xp': 0,
            'level': 0,
            'messages': 0,
            'last_message': None,
            'daily_bonus_claimed': None
        }
    
    old_level = levels_data[user_id_str]['level']
    levels_data[user_id_str]['xp'] += xp_amount
    levels_data[user_id_str]['messages'] += 1
    levels_data[user_id_str]['last_message'] = time.time()
    
    new_level = calculate_level(levels_data[user_id_str]['xp'])
    levels_data[user_id_str]['level'] = new_level
    
    save_levels()
    
    return new_level, old_level != new_level

def get_user_level_info(user_id):
    """Получает информацию об уровне пользователя"""
    user_id_str = str(user_id)
    
    if user_id_str not in levels_data:
        return {
            'xp': 0,
            'level': 0,
            'messages': 0,
            'xp_for_next': 100,
            'progress': 0
        }
    
    user_data = levels_data[user_id_str]
    current_level = user_data['level']
    current_xp = user_data['xp']
    
    xp_for_current = calculate_xp_for_level(current_level)
    xp_for_next = calculate_xp_for_level(current_level + 1)
    
    progress = ((current_xp - xp_for_current) / (xp_for_next - xp_for_current)) * 100 if xp_for_next > xp_for_current else 100
    
    return {
        'xp': current_xp,
        'level': current_level,
        'messages': user_data['messages'],
        'xp_for_next': xp_for_next - current_xp,
        'progress': progress
    }

async def process_xp_gain(user_id, channel):
    """Обрабатывает получение XP за сообщение"""
    if not Config.LEVELS_ENABLED:
        return
    
    # Проверяем кулдаун
    current_time = time.time()
    if user_id in last_xp_time:
        if current_time - last_xp_time[user_id] < Config.LEVELS_COOLDOWN_SECONDS:
            return
    
    last_xp_time[user_id] = current_time
    
    # Генерируем случайное количество XP
    xp_amount = random.randint(Config.LEVELS_XP_MIN, Config.LEVELS_XP_MAX)
    
    # Добавляем XP и проверяем повышение уровня
    new_level, level_up = add_xp(user_id, xp_amount)
    
    # Если уровень повысился, отправляем уведомление
    if level_up and new_level > 0:
        try:
            # Получаем пользователя для упоминания
            user = channel.guild.get_member(user_id)
            user_mention = user.mention if user else f"<@{user_id}>"
            
            embed = discord.Embed(
                title="🎉 Повышение уровня!",
                description=f"Поздравляем {user_mention}! Вы достигли **{new_level} уровня**!",
                color=Config.EMBED_COLOR_DEFAULT
            )
            embed.add_field(name="🔥 Новый уровень", value=str(new_level), inline=True)
            
            user_info = get_user_level_info(user_id)
            embed.add_field(name="⭐ Общий XP", value=str(user_info['xp']), inline=True)
            embed.add_field(name="💬 Сообщений", value=str(user_info['messages']), inline=True)
            
            await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления о повышении уровня: {e}")

async def check_antispam(user_id, user, guild, channel):
    """Проверяет, нарушает ли пользователь лимиты антиспама"""
    if not Config.ANTISPAM_ENABLED:
        return False
    
    current_time = time.time()
    
    # Проверяем, не замучен ли пользователь
    if user_id in muted_users:
        if current_time < muted_users[user_id]:
            return True  # Пользователь все еще замучен
        else:
            # Время мута истекло, удаляем из списка
            del muted_users[user_id]
    
    # Инициализируем список времен сообщений для нового пользователя
    if user_id not in user_message_times:
        user_message_times[user_id] = []
    
    # Удаляем старые записи (старше временного окна)
    time_window_start = current_time - Config.ANTISPAM_TIME_WINDOW
    user_message_times[user_id] = [
        msg_time for msg_time in user_message_times[user_id] 
        if msg_time > time_window_start
    ]
    
    # Добавляем текущее время
    user_message_times[user_id].append(current_time)
    
    # Проверяем, превышен ли лимит
    if len(user_message_times[user_id]) > Config.ANTISPAM_MAX_MESSAGES:
        # Мутим пользователя
        muted_users[user_id] = current_time + Config.ANTISPAM_MUTE_DURATION
        # Очищаем историю сообщений
        user_message_times[user_id] = []
        logger.warning(f"Пользователь {user_id} замучен за спам на {Config.ANTISPAM_MUTE_DURATION} секунд")
        
        # Отправляем уведомление в канал логов
        await send_antispam_notification(user, guild, channel, "mute")
        
        return True
    
    # Если пользователь приближается к лимиту, отправляем предупреждение
    if len(user_message_times[user_id]) == Config.ANTISPAM_MAX_MESSAGES:
        await send_antispam_notification(user, guild, channel, "warning")
    
    return False

# Функция отправки уведомлений об антиспаме
async def send_antispam_notification(user, guild, channel, action_type):
    """Отправляет уведомление о действиях антиспам системы в канал логов"""
    try:
        log_channel = bot.get_channel(Config.ANTISPAM_LOG_CHANNEL_ID)
        if not log_channel:
            logger.warning(f"Канал логов антиспама {Config.ANTISPAM_LOG_CHANNEL_ID} не найден")
            return
        
        current_time = discord.utils.utcnow()
        
        if action_type == "mute":
            embed = discord.Embed(
                title="🔇 Пользователь замучен за спам",
                color=Config.EMBED_COLOR_DEFAULT,
                timestamp=current_time
            )
            
            # Также отправляем уведомление в канал модерации
            try:
                # Создаем фиктивное сообщение для функции send_violation_report
                class FakeMessage:
                    def __init__(self, user, guild, channel):
                        self.author = user
                        self.guild = guild
                        self.channel = channel
                        self.id = "unknown"
                        self.content = "Спам сообщения"
                
                fake_message = FakeMessage(user, guild, channel)
                violation_type = f"Спам в связанном канале (замучен на {Config.ANTISPAM_MUTE_DURATION} сек)"
                await send_violation_report(fake_message, violation_type, f"Превышен лимит: {Config.ANTISPAM_MAX_MESSAGES} сообщений за {Config.ANTISPAM_TIME_WINDOW} секунд")
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления о спаме в канал модерации: {e}")
            embed.add_field(
                name="👤 Пользователь",
                value=f"{user.mention} (`{user.id}`)",
                inline=True
            )
            embed.add_field(
                name="🏠 Сервер",
                value=f"{guild.name} (`{guild.id}`)",
                inline=True
            )
            embed.add_field(
                name="📝 Канал",
                value=f"{channel.mention} (`{channel.id}`)",
                inline=True
            )
            embed.add_field(
                name="⏱️ Длительность мута",
                value=f"{Config.ANTISPAM_MUTE_DURATION} секунд",
                inline=True
            )
            embed.add_field(
                name="⚙️ Настройки",
                value=f"Лимит: {Config.ANTISPAM_MAX_MESSAGES} сообщений за {Config.ANTISPAM_TIME_WINDOW} секунд",
                inline=False
            )
            
        elif action_type == "warning":
            embed = discord.Embed(
                title="⚠️ Предупреждение о спаме",
                color=Config.EMBED_COLOR_DEFAULT,
                timestamp=current_time
            )
            embed.add_field(
                name="👤 Пользователь",
                value=f"{user.mention} (`{user.id}`)",
                inline=True
            )
            embed.add_field(
                name="🏠 Сервер",
                value=f"{guild.name} (`{guild.id}`)",
                inline=True
            )
            embed.add_field(
                name="📝 Канал",
                value=f"{channel.mention} (`{channel.id}`)",
                inline=True
            )
            embed.add_field(
                name="📊 Статус",
                value=f"Достиг лимита {Config.ANTISPAM_MAX_MESSAGES} сообщений за {Config.ANTISPAM_TIME_WINDOW} секунд",
                inline=False
            )
        
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text="Антиспам система", icon_url=bot.user.display_avatar.url)
        
        await log_channel.send(embed=embed)
        
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления об антиспаме: {e}")

async def send_connection_notification(member, action_type):
    """Отправляет уведомление о подключении/отключении участника"""
    if not Config.CONNECTION_NOTIFICATIONS_ENABLED:
        return
    
    # Проверяем, что это нужный сервер
    if str(member.guild.id) != Config.CONNECTION_NOTIFICATIONS_GUILD_ID:
        return
    
    try:
        log_channel = bot.get_channel(Config.CONNECTION_NOTIFICATIONS_CHANNEL_ID)
        if not log_channel:
            logger.warning(f"Канал уведомлений о подключениях {Config.CONNECTION_NOTIFICATIONS_CHANNEL_ID} не найден")
            return
        
        current_time = discord.utils.utcnow()
        
        if action_type == "join":
            embed = discord.Embed(
                title="📥 Новый участник присоединился",
                color=Config.EMBED_COLOR_DEFAULT,
                timestamp=current_time
            )
            embed.add_field(
                name="👤 Участник",
                value=f"{member.mention} (`{member.id}`)",
                inline=True
            )
            embed.add_field(
                name="📛 Имя пользователя",
                value=f"{member.name}#{member.discriminator}",
                inline=True
            )
            embed.add_field(
                name="🏠 Сервер",
                value=f"{member.guild.name} (`{member.guild.id}`)",
                inline=True
            )
            embed.add_field(
                name="📅 Аккаунт создан",
                value=f"<t:{int(member.created_at.timestamp())}:F>",
                inline=True
            )
            embed.add_field(
                name="👥 Всего участников",
                value=f"{member.guild.member_count}",
                inline=True
            )
            
        elif action_type == "leave":
            embed = discord.Embed(
                title="📤 Участник покинул сервер",
                color=Config.EMBED_COLOR_DEFAULT,
                timestamp=current_time
            )
            embed.add_field(
                name="👤 Участник",
                value=f"{member.mention} (`{member.id}`)",
                inline=True
            )
            embed.add_field(
                name="📛 Имя пользователя",
                value=f"{member.name}#{member.discriminator}",
                inline=True
            )
            embed.add_field(
                name="🏠 Сервер",
                value=f"{member.guild.name} (`{member.guild.id}`)",
                inline=True
            )
            if member.joined_at:
                embed.add_field(
                    name="📅 Присоединился",
                    value=f"<t:{int(member.joined_at.timestamp())}:F>",
                    inline=True
                )
                # Вычисляем время на сервере
                time_on_server = current_time - member.joined_at
                days = time_on_server.days
                hours, remainder = divmod(time_on_server.seconds, 3600)
                minutes, _ = divmod(remainder, 60)
                
                time_str = []
                if days > 0:
                    time_str.append(f"{days} дн.")
                if hours > 0:
                    time_str.append(f"{hours} ч.")
                if minutes > 0:
                    time_str.append(f"{minutes} мин.")
                
                embed.add_field(
                    name="⏱️ Время на сервере",
                    value=" ".join(time_str) if time_str else "Менее минуты",
                    inline=True
                )
            embed.add_field(
                name="👥 Осталось участников",
                value=f"{member.guild.member_count}",
                inline=True
            )
        
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="Система уведомлений", icon_url=bot.user.display_avatar.url)
        
        await log_channel.send(embed=embed)
        
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления о подключении/отключении: {e}")

# Функция проверки прав бота
async def check_bot_permissions(channel, notify_admin=True):
    """Проверяет права бота в канале и уведомляет администратора при их отсутствии"""
    required_permissions = {
        'send_messages': 'Отправка сообщений',
        'manage_webhooks': 'Управление вебхуками', 
        'read_message_history': 'Чтение истории сообщений',
        'attach_files': 'Прикрепление файлов'
    }
    
    permissions = channel.permissions_for(channel.guild.me)
    missing_permissions = []
    
    for perm_name, perm_description in required_permissions.items():
        if not getattr(permissions, perm_name):
            missing_permissions.append(perm_description)
    
    if missing_permissions and notify_admin:
        # Ищем администратора для уведомления
        admin_channel = None
        
        # Ищем канал модерации
        for ch in channel.guild.text_channels:
            if any(keyword in ch.name.lower() for keyword in ['модерация', 'модер', 'admin', 'управление', 'настройки']):
                if ch.permissions_for(channel.guild.me).send_messages:
                    admin_channel = ch
                    break
        
        # Если не найден, используем системный канал
        if not admin_channel and channel.guild.system_channel:
            if channel.guild.system_channel.permissions_for(channel.guild.me).send_messages:
                admin_channel = channel.guild.system_channel
        
        # Если и системного канала нет, используем текущий канал
        if not admin_channel and permissions.send_messages:
            admin_channel = channel
        
        if admin_channel:
            try:
                embed = discord.Embed(
                    title="⚠️ Недостаточно прав у бота",
                    description=f"Боту не хватает прав в канале {channel.mention} для корректной работы.",
                    color=Config.EMBED_COLOR_DEFAULT
                )
                
                embed.add_field(
                    name="❌ Отсутствующие права",
                    value="\n".join([f"• {perm}" for perm in missing_permissions]),
                    inline=False
                )
                
                embed.add_field(
                    name="🔧 Как исправить",
                    value="1. Перейдите в настройки сервера\n2. Откройте раздел 'Роли'\n3. Найдите роль бота\n4. Предоставьте недостающие права\n\nИли предоставьте права напрямую в настройках канала.",
                    inline=False
                )
                
                embed.add_field(
                    name="📋 Все необходимые права",
                    value="• Отправка сообщений\n• Управление вебхуками\n• Чтение истории сообщений\n• Прикрепление файлов",
                    inline=False
                )
                
                embed.set_footer(text="Без этих прав бот не сможет корректно пересылать сообщения между каналами")
                
                await admin_channel.send(embed=embed)
                logger.warning(f"Отправлено уведомление о недостающих правах в канале {channel.name} на сервере {channel.guild.name}")
                
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления о правах: {e}")
    
    return len(missing_permissions) == 0, missing_permissions

# Периодическая проверка прав бота
@tasks.loop(minutes=30)
async def periodic_permissions_check():
    """Периодически проверяет права бота во всех связанных каналах"""
    if not bot.is_ready():
        return
        
    logger.info("Начинаем периодическую проверку прав бота...")
    
    channels_with_issues = 0
    total_channels = len(linked_channels)
    
    for channel_id, channel_info in linked_channels.items():
        try:
            channel = bot.get_channel(int(channel_id))
            if channel:
                has_permissions, missing_perms = await check_bot_permissions(channel, notify_admin=True)
                if not has_permissions:
                    channels_with_issues += 1
                    logger.warning(f"Проблемы с правами в канале {channel.name} ({channel.guild.name}): {', '.join(missing_perms)}")
            else:
                logger.warning(f"Канал {channel_id} недоступен (возможно, удален)")
        except Exception as e:
            logger.error(f"Ошибка при проверке прав в канале {channel_id}: {e}")
    
    if channels_with_issues > 0:
        logger.warning(f"Обнаружены проблемы с правами в {channels_with_issues} из {total_channels} каналов")
    else:
        logger.info(f"Проверка завершена. Все {total_channels} каналов имеют необходимые права")

@periodic_permissions_check.before_loop
async def before_permissions_check():
    """Ждем готовности бота перед началом периодической проверки"""
    await bot.wait_until_ready()

# Периодическая очистка данных антиспама
@tasks.loop(minutes=10)
async def cleanup_antispam_data():
    """Периодическая очистка устаревших данных антиспама"""
    if not bot.is_ready() or not Config.ANTISPAM_ENABLED:
        return
    
    current_time = time.time()
    
    # Очищаем истекшие муты
    expired_mutes = [user_id for user_id, mute_end in muted_users.items() if mute_end <= current_time]
    for user_id in expired_mutes:
        del muted_users[user_id]
    
    # Очищаем старые записи времен сообщений
    time_window_start = current_time - Config.ANTISPAM_TIME_WINDOW
    users_to_clean = []
    
    for user_id, message_times in user_message_times.items():
        # Удаляем старые записи
        user_message_times[user_id] = [
            msg_time for msg_time in message_times 
            if msg_time > time_window_start
        ]
        
        # Если у пользователя не осталось записей, помечаем для удаления
        if not user_message_times[user_id]:
            users_to_clean.append(user_id)
    
    # Удаляем пустые записи
    for user_id in users_to_clean:
        del user_message_times[user_id]
    
    if expired_mutes or users_to_clean:
        logger.debug(f"Очистка антиспам данных: {len(expired_mutes)} истекших мутов, {len(users_to_clean)} пустых записей")

@cleanup_antispam_data.before_loop
async def before_cleanup_antispam():
    """Ждем готовности бота перед началом очистки антиспам данных"""
    await bot.wait_until_ready()

@bot.event
async def on_ready():
    """Событие готовности бота"""
    logger.info(f'{bot.user} подключился к Discord!')
    logger.info(f'Бот активен на {len(bot.guilds)} серверах')
    
    # Синхронизируем slash команды
    try:
        synced = await bot.tree.sync()
        logger.info(f'Синхронизировано {len(synced)} slash команд')
    except Exception as e:
        logger.error(f'Ошибка при синхронизации slash команд: {e}')
    
    # Проверяем доступность каналов при запуске
    if Config.AUTO_CLEANUP_CHANNELS:
        await cleanup_invalid_channels()
    
    # Устанавливаем статус бота
    activity = discord.Activity(type=discord.ActivityType.watching, name=f"{len(linked_channels)} связанных каналов")
    await bot.change_presence(activity=activity)
    
    # Запускаем периодическую проверку прав
    if not periodic_permissions_check.is_running():
        periodic_permissions_check.start()
        logger.info("Запущена периодическая проверка прав бота (каждые 30 минут)")
    
    # Запускаем периодическую очистку антиспам данных
    if Config.ANTISPAM_ENABLED and not cleanup_antispam_data.is_running():
        cleanup_antispam_data.start()
        logger.info("Запущена периодическая очистка антиспам данных (каждые 10 минут)")
    
    # Отправляем информацию о боте в указанный канал (только один раз)
    await send_bot_info_once()

async def send_bot_info_once():
    """Отправляет информацию о боте в указанный канал только один раз"""
    target_channel_id = 1387904918433693736
    bot_info_sent_file = "bot_info_sent.txt"
    
    # Проверяем, была ли уже отправлена информация
    if os.path.exists(bot_info_sent_file):
        logger.info("Информация о боте уже была отправлена ранее")
        return
    
    try:
        channel = bot.get_channel(target_channel_id)
        if not channel:
            logger.error(f"Канал {target_channel_id} не найден")
            return
        
        # Создаем красивое embed сообщение с информацией о боте
        embed = discord.Embed(
            title="🤖 Relay Bot - Межсерверная связь",
            description="Межсерверный мост для каналов с поддержкой RelayRU и RelayEN сетей",
            color=0x00ff88
        )
        
        embed.add_field(
            name="⚡ Возможности",
            value="• Межсерверные сети каналов\n• Пересылка сообщений и файлов\n• Автоматический мониторинг прав\n• Антиспам защита\n• Уведомления о подключениях/отключениях\n• Система чёрного списка\n• Система уровней с отображением рангов\n• Красивое оформление сообщений",
            inline=False
        )
        
        embed.add_field(
            name="📋 Основные команды",
            value="`/создать-сеть` - создать новую сеть\n`/связать` - подключить канал к существующей сети\n`/отключить` - отключить канал\n`/поиск-сети` - показать доступные сети\n`/проверить_права` - проверить права бота\n`/бот-инфо` - информация о боте\n\n💡 **Важно:** Название сети может быть любым и не обязательно должно совпадать с названием канала!",
            inline=False
        )
        
        embed.add_field(
            name="👨‍💻 Разработчик",
            value="brqden",
            inline=True
        )
        
        embed.add_field(
            name="🔗 Пригласить бота",
            value="[Добавить на сервер](https://discord.com/oauth2/authorize?client_id=1126222332835397633)",
            inline=False
        )
        
        embed.set_footer(text="Relay Bot | Соединяем серверы Discord")
        embed.set_thumbnail(url=bot.user.avatar.url if bot.user.avatar else None)
        
        await channel.send(embed=embed)
        
        # Создаем файл-маркер, что информация была отправлена
        with open(bot_info_sent_file, 'w', encoding='utf-8') as f:
            f.write(f"Bot info sent at {datetime.now()}")
        
        logger.info(f"Информация о боте успешно отправлена в канал {target_channel_id}")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке информации о боте: {e}")

async def cleanup_invalid_channels():
    """Удаляет недоступные каналы из конфигурации"""
    global linked_channels
    valid_channels = {}
    removed_count = 0
    
    for channel_id, channel_info in linked_channels.items():
        channel = bot.get_channel(int(channel_id))
        if channel:
            valid_channels[channel_id] = channel_info
        else:
            guild_name = channel_info.get("guild_name", "Unknown") if isinstance(channel_info, dict) else "Unknown"
            logger.warning(f'Канал {channel_id} ({guild_name}) недоступен и будет удален')
            removed_count += 1
    
    if removed_count > 0:
        linked_channels = valid_channels
        save_channels_config(linked_channels)
        logger.info(f"Удалено {removed_count} недоступных каналов")

async def check_raid_protection(message):
    """Проверяет сообщение на наличие рейд-контента (массовые упоминания и Discord инвайты)"""
    if not Config.RAID_PROTECTION_ENABLED:
        return False
    
    content = message.content.lower()
    
    # Проверяем массовые упоминания @everyone и @here
    if Config.RAID_PROTECTION_BLOCK_MASS_MENTIONS and ('@everyone' in content or '@here' in content):
        try:
            await message.delete()
            logger.warning(f"Удалено сообщение с массовым упоминанием от {message.author} ({message.author.id}) в {message.guild.name}#{message.channel.name}")
            
            # Отправляем уведомление о нарушении
            violation_type = "Массовое упоминание (@everyone/@here)"
            await send_violation_report(message, violation_type, message.content)
            
            # Отправляем предупреждение пользователю в ЛС
            try:
                embed = discord.Embed(
                    title="⚠️ Нарушение правил",
                    description="Ваше сообщение было удалено за использование массовых упоминаний (@everyone/@here).",
                    color=Config.EMBED_COLOR_WARNING
                )
                embed.set_footer(text=f"Сервер: {message.guild.name} • Канал: #{message.channel.name}")
                await message.author.send(embed=embed)
            except discord.Forbidden:
                pass  # Не можем отправить в ЛС
            
            return True
        except discord.Forbidden:
            logger.warning(f"Нет прав на удаление сообщения с массовым упоминанием от {message.author}")
    
    # Проверяем Discord инвайты
    if Config.RAID_PROTECTION_BLOCK_DISCORD_INVITES and ('discord.gg/' in content or 'discordapp.com/invite/' in content or 'discord.com/invite/' in content):
        try:
            await message.delete()
            logger.warning(f"Удалено сообщение с Discord инвайтом от {message.author} ({message.author.id}) в {message.guild.name}#{message.channel.name}")
            
            # Отправляем уведомление о нарушении
            violation_type = "Размещение Discord инвайта"
            await send_violation_report(message, violation_type, message.content)
            
            # Отправляем предупреждение пользователю в ЛС
            try:
                embed = discord.Embed(
                    title="⚠️ Нарушение правил",
                    description="Ваше сообщение было удалено за размещение Discord инвайта.",
                    color=Config.EMBED_COLOR_WARNING
                )
                embed.set_footer(text=f"Сервер: {message.guild.name} • Канал: #{message.channel.name}")
                await message.author.send(embed=embed)
            except discord.Forbidden:
                pass  # Не можем отправить в ЛС
            
            return True
        except discord.Forbidden:
            logger.warning(f"Нет прав на удаление сообщения с Discord инвайтом от {message.author}")
    
    return False

@bot.event
async def on_message(message):
    """Обработка входящих сообщений"""
    # Игнорируем сообщения от ботов
    if message.author.bot:
        return
    
    # Система чёрного списка - обработка каналов модерации
    if Config.BLACKLIST_ENABLED:
        # Проверяем канал блокировки
        if message.channel.id == Config.BLACKLIST_BAN_CHANNEL_ID:
            # Проверяем, есть ли у автора роль модератора
            if any(role.id == Config.BLACKLIST_MODERATOR_ROLE_ID for role in message.author.roles):
                # Пытаемся извлечь ID пользователя из сообщения
                try:
                    user_id = int(message.content.strip())
                    if add_to_blacklist(user_id):
                        embed = discord.Embed(
                            title="🚫 Пользователь заблокирован",
                            description=f"Пользователь с ID `{user_id}` добавлен в чёрный список.",
                            color=Config.EMBED_COLOR_DEFAULT
                        )
                        embed.add_field(name="Модератор", value=message.author.mention, inline=True)
                        embed.set_footer(text="Система чёрного списка")
                        await message.channel.send(embed=embed)
                    else:
                        await message.channel.send("❌ Ошибка при добавлении пользователя в чёрный список.")
                except ValueError:
                    await message.channel.send("❌ Неверный формат ID пользователя. Отправьте только числовой ID.")
            return
        
        # Проверяем канал разблокировки
        elif message.channel.id == Config.BLACKLIST_UNBAN_CHANNEL_ID:
            # Проверяем, есть ли у автора роль модератора
            if any(role.id == Config.BLACKLIST_MODERATOR_ROLE_ID for role in message.author.roles):
                # Пытаемся извлечь ID пользователя из сообщения
                try:
                    user_id = int(message.content.strip())
                    if remove_from_blacklist(user_id):
                        embed = discord.Embed(
                            title="✅ Пользователь разблокирован",
                            description=f"Пользователь с ID `{user_id}` удалён из чёрного списка.",
                            color=Config.EMBED_COLOR_DEFAULT
                        )
                        embed.add_field(name="Модератор", value=message.author.mention, inline=True)
                        embed.set_footer(text="Система чёрного списка")
                        await message.channel.send(embed=embed)
                    else:
                        await message.channel.send("❌ Пользователь не найден в чёрном списке.")
                except ValueError:
                    await message.channel.send("❌ Неверный формат ID пользователя. Отправьте только числовой ID.")
            return
        
        # Проверяем, находится ли автор сообщения в чёрном списке
        if is_blacklisted(message.author.id):
            # Отправляем уведомление о нарушении
            violation_type = "Попытка отправки сообщения заблокированным пользователем"
            await send_violation_report(message, violation_type, message.content)
            
            # Удаляем сообщение от заблокированного пользователя
            try:
                await message.delete()
                logger.info(f"Сообщение от заблокированного пользователя {message.author} ({message.author.id}) удалено")
            except discord.Forbidden:
                logger.warning(f"Нет прав на удаление сообщения от заблокированного пользователя {message.author}")
            return
    
    # Анти-рейд защита: проверяем массовые упоминания и Discord инвайты
    if await check_raid_protection(message):
        return
    
    # Проверяем антиспам для связанных каналов
    channel_id = str(message.channel.id)
    if channel_id in linked_channels:
        # Проверяем антиспам
        if await check_antispam(message.author.id, message.author, message.guild, message.channel):
            # Пользователь нарушил лимиты, удаляем сообщение и отправляем предупреждение
            try:
                await message.delete()
                
                # Отправляем предупреждение в личные сообщения
                try:
                    embed = discord.Embed(
                        title="⚠️ Антиспам система",
                        description=f"Вы отправляете сообщения слишком часто!\n\nВы временно заблокированы на **{Config.ANTISPAM_MUTE_DURATION} секунд**.\n\nЛимит: **{Config.ANTISPAM_MAX_MESSAGES} сообщений** за **{Config.ANTISPAM_TIME_WINDOW} секунд**.",
                        color=Config.EMBED_COLOR_WARNING
                    )
                    embed.set_footer(text=f"Сервер: {message.guild.name} • Канал: #{message.channel.name}")
                    await message.author.send(embed=embed)
                except discord.Forbidden:
                    # Если не можем отправить в ЛС, отправляем в канал (эфемерно)
                    pass
                
                logger.info(f"Сообщение от {message.author} удалено за спам в {message.guild.name}#{message.channel.name}")
                return
            except discord.Forbidden:
                logger.warning(f"Нет прав на удаление сообщения от {message.author} в {message.guild.name}#{message.channel.name}")
                return
            except Exception as e:
                logger.error(f"Ошибка при обработке антиспама: {e}")
                return
    
    # Логируем сообщения если включено
    if Config.LOG_MESSAGES:
        logger.debug(f"Сообщение от {message.author} в {message.guild.name}#{message.channel.name}: {message.content[:100]}")
    
    # Начисляем XP за сообщение
    if Config.LEVELS_ENABLED:
        await process_xp_gain(message.author.id, message.channel)
    
    # Проверяем, является ли канал связанным (повторная проверка после антиспама)
    if channel_id in linked_channels:
        await relay_message(message)
    
    # Обрабатываем команды
    await bot.process_commands(message)

@bot.event
async def on_member_join(member):
    """Событие присоединения нового участника к серверу"""
    # Отправляем уведомление о подключении
    await send_connection_notification(member, "join")
    
    # Проверяем, включена ли автоматическая выдача ролей
    if not Config.AUTO_ROLE_ENABLED:
        return
    
    # Проверяем, что это нужный сервер
    if str(member.guild.id) != Config.AUTO_ROLE_GUILD_ID:
        return
    
    try:
        # Получаем роль для выдачи
        role = member.guild.get_role(int(Config.AUTO_ROLE_ID))
        if not role:
            logger.error(f"Роль с ID {Config.AUTO_ROLE_ID} не найдена на сервере {member.guild.name}")
            return
        
        # Проверяем права бота на выдачу ролей
        if not member.guild.me.guild_permissions.manage_roles:
            logger.error(f"У бота нет прав на управление ролями на сервере {member.guild.name}")
            return
        
        # Проверяем, что роль бота выше выдаваемой роли
        if member.guild.me.top_role <= role:
            logger.error(f"Роль бота ниже или равна выдаваемой роли {role.name} на сервере {member.guild.name}")
            return
        
        # Выдаем роль новому участнику
        await member.add_roles(role, reason="Автоматическая выдача роли новому участнику")
        logger.info(f"Выдана роль '{role.name}' пользователю {member.display_name} ({member.id}) на сервере {member.guild.name}")
        
    except discord.Forbidden:
        logger.error(f"Недостаточно прав для выдачи роли пользователю {member.display_name} на сервере {member.guild.name}")
    except discord.HTTPException as e:
        logger.error(f"Ошибка HTTP при выдаче роли пользователю {member.display_name}: {e}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка при выдаче роли пользователю {member.display_name}: {e}")

@bot.event
async def on_member_remove(member):
    """Событие покидания участником сервера"""
    # Отправляем уведомление об отключении
    await send_connection_notification(member, "leave")

@bot.event
async def on_guild_join(guild):
    """Событие добавления бота на новый сервер"""
    logger.info(f'Бот добавлен на сервер: {guild.name} (ID: {guild.id})')
    
    # Ищем канал модерации или системный канал
    moderation_channel = None
    
    # Приоритет поиска каналов:
    # 1. Канал с названием содержащим "модерация", "admin", "управление"
    # 2. Системный канал сервера
    # 3. Первый текстовый канал, где бот может писать
    
    # Поиск канала модерации по названию
    for channel in guild.text_channels:
        if any(keyword in channel.name.lower() for keyword in ['модерация', 'модер', 'admin', 'управление', 'настройки']):
            if channel.permissions_for(guild.me).send_messages:
                moderation_channel = channel
                break
    
    # Если не найден, используем системный канал
    if not moderation_channel and guild.system_channel:
        if guild.system_channel.permissions_for(guild.me).send_messages:
            moderation_channel = guild.system_channel
    
    # Если и системного канала нет, ищем первый доступный текстовый канал
    if not moderation_channel:
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                moderation_channel = channel
                break
    
    # Отправляем приветственное сообщение с инструкциями
    if moderation_channel:
        try:
            embed = discord.Embed(
                title="🤖 Добро пожаловать! Бот успешно добавлен",
                description="Спасибо за добавление бота для связи каналов между серверами!",
                color=0x00ff00
            )
            
            embed.add_field(
                name="📋 Основные команды",
                value="• `/связать <название_сети>` - связать канал с сетью\n• `/отключить` - отключить канал от сети",
                inline=False
            )
            
            embed.add_field(
                name="🌐 Готовые сети",
                value="**RelayRU** - для СНГ аудитории: `/связать RelayRU`\n**RelayEN** - для англоговорящих: `/связать RelayEN`\n\nОбе сети объединяют множество серверов!",
                inline=False
            )
            
            embed.add_field(
                name="⚙️ Как настроить собственную сеть",
                value="1. Перейдите в канал, который хотите связать\n2. Используйте команду `/связать <ваше_название>` с уникальным названием сети\n3. Повторите на других серверах с тем же названием сети\n4. Сообщения будут автоматически пересылаться между связанными каналами\n\n💡 **Важно:** Название сети может быть любым и не обязательно должно совпадать с названием канала!",
                inline=False
            )
            
            embed.add_field(
                name="🔧 Требуемые разрешения",
                value="• Отправка сообщений\n• Управление вебхуками\n• Чтение истории сообщений\n• Прикрепление файлов",
                inline=False
            )
            
            embed.add_field(
                name="📚 Дополнительная информация",
                value="Подробные примеры и решение проблем можно найти в документации бота.",
                inline=False
            )
            
            embed.set_footer(text=f"Бот активен на {len(bot.guilds)} серверах")
            
            await moderation_channel.send(embed=embed)
            logger.info(f'Отправлены инструкции в канал {moderation_channel.name} на сервере {guild.name}')
            
        except Exception as e:
            logger.error(f'Ошибка при отправке приветственного сообщения на сервере {guild.name}: {e}')
    else:
        logger.warning(f'Не удалось найти подходящий канал для отправки инструкций на сервере {guild.name}')
    
    # Отправка уведомления о добавлении бота в специальный канал
    try:
        notification_guild_id = 1387900625324478506
        notification_channel_id = 1388121874529255596
        
        notification_guild = bot.get_guild(notification_guild_id)
        if notification_guild:
            notification_channel = notification_guild.get_channel(notification_channel_id)
            if notification_channel:
                # Создаем красивый embed для уведомления
                notification_embed = discord.Embed(
                    title="🎉 Бот добавлен на новый сервер!",
                    description=f"Relay Bot был успешно добавлен на сервер **{guild.name}**",
                    color=Config.EMBED_COLOR_DEFAULT,
                    timestamp=discord.utils.utcnow()
                )
                
                notification_embed.add_field(
                    name="📊 Информация о сервере",
                    value=f"**Название:** {guild.name}\n**ID:** {guild.id}\n**Участников:** {guild.member_count}\n**Создан:** <t:{int(guild.created_at.timestamp())}:D>",
                    inline=True
                )
                
                notification_embed.add_field(
                    name="📈 Статистика бота",
                    value=f"**Всего серверов:** {len(bot.guilds)}\n**Всего пользователей:** {sum(g.member_count for g in bot.guilds if g.member_count)}",
                    inline=True
                )
                
                # Добавляем иконку сервера если есть
                if guild.icon:
                    notification_embed.set_thumbnail(url=guild.icon.url)
                
                notification_embed.set_footer(
                    text=f"Добавлен пользователем: {guild.owner.display_name if guild.owner else 'Неизвестно'}",
                    icon_url=guild.owner.avatar.url if guild.owner and guild.owner.avatar else None
                )
                
                await notification_channel.send(embed=notification_embed)
                logger.info(f'Отправлено уведомление о добавлении на сервер {guild.name}')
            else:
                logger.warning(f'Канал уведомлений {notification_channel_id} не найден')
        else:
            logger.warning(f'Сервер уведомлений {notification_guild_id} не найден')
    except Exception as e:
        logger.error(f'Ошибка при отправке уведомления о добавлении бота: {e}')

@bot.event
async def on_guild_remove(guild):
    """Событие удаления бота с сервера"""
    logger.info(f'Бот удален с сервера: {guild.name} (ID: {guild.id})')
    
    # Удаляем все связанные каналы этого сервера
    global linked_channels
    channels_to_remove = []
    
    for channel_id, channel_info in linked_channels.items():
        if isinstance(channel_info, dict) and channel_info.get('guild_id') == str(guild.id):
            channels_to_remove.append(channel_id)
    
    if channels_to_remove:
        for channel_id in channels_to_remove:
            network_name = linked_channels[channel_id]['network']
            channel_name = linked_channels[channel_id].get('channel_name', 'Неизвестно')
            del linked_channels[channel_id]
            logger.info(f'Удален канал {channel_name} (ID: {channel_id}) из сети "{network_name}"')
        
        save_channels_config(linked_channels)
        logger.info(f'Удалено {len(channels_to_remove)} каналов с сервера {guild.name}')

async def relay_message(message):
    """Пересылает сообщение во все связанные каналы как webhook с именем пользователя"""
    try:
        channel_id = str(message.channel.id)
        current_channel_info = linked_channels[channel_id]
        network_name = current_channel_info['network']
        
        # Проверяем права бота в исходном канале
        has_permissions, missing_perms = await check_bot_permissions(message.channel, notify_admin=True)
        if not has_permissions:
            logger.warning(f"Недостаточно прав в канале {message.channel.name} на сервере {message.guild.name}. Отсутствуют: {', '.join(missing_perms)}")
            return
        
        # Проверяем длину сообщения и удаляем ссылки
        content = message.content if message.content else "*Сообщение без текста*"
        
        # Отладочная информация
        logger.info(f"Обработка сообщения: content='{message.content}', attachments={len(message.attachments)}, embeds={len(message.embeds)}")
        
        # Удаляем ссылки из контента, если есть текст, но НЕ удаляем если есть вложения (гифки, файлы) или embeds
        if message.content and not message.attachments and not message.embeds:
            # Проверяем, есть ли ссылки в сообщении
            url_pattern = r'(?:(?:https?|ftp)://|www\.)(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
            found_links = re.findall(url_pattern, message.content)
            
            if found_links:
                # Отправляем уведомление о нарушении
                violation_type = f"Отправка ссылок в связанном канале ({len(found_links)} ссылок)"
                await send_violation_report(message, violation_type, message.content)
                logger.info(f"Обнаружены ссылки от {message.author.name}: {found_links}")
            
            logger.info(f"Применяем remove_links_from_text к: '{content}'")
            content = remove_links_from_text(content)
            logger.info(f"Результат после remove_links_from_text: '{content}'")
        else:
            logger.info(f"НЕ применяем remove_links_from_text (attachments: {len(message.attachments)}, embeds: {len(message.embeds)})")
        
        if len(content) > 2000:
            content = content[:1997] + "..."
        
        # Информация о сервере убрана по запросу пользователя
        # if content:
        #     content = f"{content}\n\n*Из {message.guild.name} • #{message.channel.name}*"
        
        # Отправляем сообщение во все связанные каналы той же сети
        sent_count = 0
        total_network_channels = 0
        
        # Подсчитываем общее количество каналов в сети для диагностики
        for other_channel_id, other_channel_info in linked_channels.items():
            if other_channel_info['network'] == network_name:
                total_network_channels += 1
        
        logger.debug(f"Всего каналов в сети '{network_name}': {total_network_channels}")
        
        for other_channel_id, other_channel_info in linked_channels.items():
            if other_channel_id != channel_id and other_channel_info['network'] == network_name:
                try:
                    target_channel = bot.get_channel(int(other_channel_id))
                    if target_channel:
                        # Проверяем права бота в целевом канале
                        has_permissions, missing_perms = await check_bot_permissions(target_channel, notify_admin=True)
                        if not has_permissions:
                            logger.warning(f"Недостаточно прав в целевом канале {target_channel.name} на сервере {target_channel.guild.name}. Пропускаем.")
                            continue
                        # Создаем или получаем webhook для канала
                        webhooks = await target_channel.webhooks()
                        webhook = None
                        
                        # Ищем существующий webhook бота
                        for wh in webhooks:
                            if wh.user == bot.user:
                                webhook = wh
                                break
                        
                        # Создаем новый webhook если не найден
                        if webhook is None:
                            try:
                                webhook = await target_channel.create_webhook(name="Channel Bridge")
                            except discord.Forbidden:
                                # Если нет прав на создание webhook, отправляем обычным сообщением
                                user_level_info = get_user_level_info(message.author.id)
                                level = user_level_info['level']
                                
                                if Config.LEVELS_ENABLED and level > 0:
                                    display_name = f"{message.author.display_name} 🔥{level}"
                                else:
                                    display_name = message.author.display_name
                                
                                await target_channel.send(f"**{display_name}**: {content}")
                                webhook = None
                        
                        if webhook:
                            # Получаем уровень пользователя для отображения
                            user_level_info = get_user_level_info(message.author.id)
                            level = user_level_info['level']
                            
                            # Формируем имя с уровнем
                            if Config.LEVELS_ENABLED and level > 0:
                                display_name = f"{message.author.display_name} 🔥{level}"
                            else:
                                display_name = message.author.display_name
                            
                            # Отправляем сообщение через webhook с именем и аватаром пользователя
                            await webhook.send(
                                content=content,
                                username=display_name,
                                avatar_url=message.author.display_avatar.url
                            )
                        
                        # Пересылаем вложения
                        for attachment in message.attachments:
                            if attachment.size <= Config.MAX_FILE_SIZE:
                                try:
                                    file_data = await attachment.read()
                                    file = discord.File(io.BytesIO(file_data), filename=attachment.filename)
                                    
                                    if webhook:
                                        await webhook.send(
                                            file=file,
                                            username=message.author.display_name,
                                            avatar_url=message.author.display_avatar.url
                                        )
                                    else:
                                        await target_channel.send(f"📎 **{message.author.display_name}** отправил файл:", file=file)
                                except Exception as e:
                                    logger.error(f"Ошибка при пересылке вложения: {e}")
                                    error_msg = f"❌ Не удалось переслать файл: {attachment.filename}"
                                    if webhook:
                                        await webhook.send(
                                            content=error_msg,
                                            username=message.author.display_name,
                                            avatar_url=message.author.display_avatar.url
                                        )
                                    else:
                                        await target_channel.send(error_msg)
                            else:
                                size_msg = f"📎 Файл слишком большой: {attachment.filename} ({attachment.size} байт)"
                                if webhook:
                                    await webhook.send(
                                        content=size_msg,
                                        username=message.author.display_name,
                                        avatar_url=message.author.display_avatar.url
                                    )
                                else:
                                    await target_channel.send(size_msg)
                        
                        sent_count += 1
                        logger.debug(f"Сообщение отправлено в канал {target_channel.guild.name}#{target_channel.name}")
                    else:
                        logger.warning(f"Канал {other_channel_id} недоступен")
                except Exception as e:
                    logger.error(f"Ошибка при отправке сообщения в канал {other_channel_id}: {e}")
        
        logger.info(f"Сообщение от {message.author} переслано в {sent_count} из {total_network_channels-1} возможных каналов сети '{network_name}'")
        
    except Exception as e:
        logger.error(f"Ошибка при пересылке сообщения: {e}")

# Slash команда для создания новой сети
@bot.tree.command(name="создать-сеть", description="Создать новую сеть и подключить к ней канал (название сети может отличаться от названия канала)")
@app_commands.describe(network_name="Имя новой сети (может быть любым, не обязательно как канал)")
async def slash_create_network(interaction: discord.Interaction, network_name: str):
    """Slash команда для создания новой сети"""
    # Откладываем ответ для избежания таймаута
    await interaction.response.defer()
    
    # Проверяем права
    if not interaction.user.guild_permissions.manage_channels:
        embed = discord.Embed(
            title="❌ Недостаточно прав",
            description="У вас нет прав для управления каналами.",
            color=Config.EMBED_COLOR_ERROR
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Очищаем имя сети от Discord упоминаний
    import re
    network_name = re.sub(r'<[#@&!][0-9]+>', '', network_name).strip()
    
    if not network_name:
        embed = discord.Embed(
            title="❌ Ошибка",
            description="Имя сети не может быть пустым или состоять только из упоминаний Discord.",
            color=Config.EMBED_COLOR_ERROR
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    channel_id = str(interaction.channel.id)
    
    # Проверяем права бота в канале
    has_permissions, missing_perms = await check_bot_permissions(interaction.channel, notify_admin=False)
    if not has_permissions:
        embed = discord.Embed(
            title="⚠️ Недостаточно прав у бота",
            description=f"Боту не хватает прав в канале {interaction.channel.mention} для корректной работы.",
            color=Config.EMBED_COLOR_DEFAULT
        )
        
        if missing_perms:
            embed.add_field(name="Отсутствующие права", value="\n".join(missing_perms), inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    if channel_id in linked_channels:
        current_network = linked_channels[channel_id]['network']
        embed = discord.Embed(
            title="⚠️ Канал уже связан",
            description=f"Канал уже связан с сетью `{current_network}`. Используйте `/отключить` для отключения.",
            color=Config.EMBED_COLOR_WARNING
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Проверяем, существует ли уже сеть с таким именем
    network_exists = any(ch_info['network'] == network_name for ch_info in linked_channels.values())
    if network_exists:
        embed = discord.Embed(
            title="⚠️ Сеть уже существует",
            description=f"Сеть с именем `{network_name}` уже существует. Используйте `/связать` для подключения к существующей сети или выберите другое имя.",
            color=Config.EMBED_COLOR_WARNING
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    # Проверяем, есть ли уже канал с другой сетью на текущем сервере (1 сеть = 1 сервер)
    # Исключение для привилегированного сервера
    current_guild_id = interaction.guild.id
    privileged_guild_id = 1387900625324478506  # Сервер с иммунитетом
    
    if current_guild_id != privileged_guild_id:
        for existing_channel_id, existing_channel_info in linked_channels.items():
            if existing_channel_info.get('guild_id') == current_guild_id:
                existing_network = existing_channel_info['network']
                embed = discord.Embed(
                    title="⚠️ Сервер уже подключен к сети",
                    description=f"На этом сервере уже есть канал, подключенный к сети `{existing_network}`. \n\nОдин сервер может быть подключен только к одной сети через один канал.",
                    color=Config.EMBED_COLOR_WARNING
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
    
    # Создаём новую сеть и добавляем канал
    linked_channels[channel_id] = {
        'network': network_name,
        'guild_id': interaction.guild.id,
        'guild_name': interaction.guild.name,
        'channel_name': interaction.channel.name,
        'linked_at': datetime.utcnow().isoformat(),
        'linked_by': str(interaction.user.id)
    }
    
    save_channels_config(linked_channels)
    
    embed = discord.Embed(
        title="✅ Сеть создана",
        description=f"Новая сеть `{network_name}` успешно создана и канал подключен к ней!",
        color=Config.EMBED_COLOR_SUCCESS
    )
    embed.add_field(name="Сеть", value=network_name, inline=True)
    embed.add_field(name="Создатель", value=interaction.user.mention, inline=True)
    embed.add_field(name="Канал", value=interaction.channel.mention, inline=True)
    
    await interaction.followup.send(embed=embed)
    
    logger.info(f"Создана новая сеть '{network_name}' пользователем {interaction.user} в канале {interaction.guild.name}#{interaction.channel.name}")
    
    # Обновляем статус бота
    activity = discord.Activity(type=discord.ActivityType.watching, name=f"{len(linked_channels)} связанных каналов")
    await bot.change_presence(activity=activity)

# Slash команда для связывания каналов
@bot.tree.command(name="связать", description="Подключить канал к существующей сети (название сети может отличаться от названия канала)")
@app_commands.describe(network_name="Имя существующей сети для подключения (может быть любым)")
async def slash_link_channel(interaction: discord.Interaction, network_name: str):
    """Slash команда для связывания канала с сетью"""
    # Проверяем права
    if not interaction.user.guild_permissions.manage_channels:
        embed = discord.Embed(
            title="❌ Недостаточно прав",
            description="У вас нет прав для управления каналами.",
            color=Config.EMBED_COLOR_ERROR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Очищаем имя сети от Discord упоминаний
    import re
    network_name = re.sub(r'<[#@&!][0-9]+>', '', network_name).strip()
    
    if not network_name:
        embed = discord.Embed(
            title="❌ Ошибка",
            description="Имя сети не может быть пустым или состоять только из упоминаний Discord.",
            color=Config.EMBED_COLOR_ERROR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    channel_id = str(interaction.channel.id)
    
    # Проверяем права бота в канале
    has_permissions, missing_perms = await check_bot_permissions(interaction.channel, notify_admin=False)
    if not has_permissions:
        embed = discord.Embed(
            title="⚠️ Недостаточно прав у бота",
            description=f"Боту не хватает прав в этом канале для корректной работы.",
            color=Config.EMBED_COLOR_WARNING
        )
        
        embed.add_field(
            name="❌ Отсутствующие права",
            value="\n".join([f"• {perm}" for perm in missing_perms]),
            inline=False
        )
        
        embed.add_field(
            name="🔧 Необходимые права",
            value="• Отправка сообщений\n• Управление вебхуками\n• Чтение истории сообщений\n• Прикрепление файлов",
            inline=False
        )
        
        embed.set_footer(text="Предоставьте боту необходимые права и попробуйте снова")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    if channel_id in linked_channels:
        current_network = linked_channels[channel_id]['network']
        embed = discord.Embed(
            title="⚠️ Канал уже связан",
            description=f"Канал уже связан с сетью `{current_network}`. Используйте `/отключить` для отключения.",
            color=Config.EMBED_COLOR_WARNING
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Проверяем, существует ли сеть с таким именем
    network_exists = any(ch_info['network'] == network_name for ch_info in linked_channels.values())
    if not network_exists:
        embed = discord.Embed(
            title="❌ Сеть не найдена",
            description=f"Сеть с именем `{network_name}` не существует. Используйте `/создать-сеть` для создания новой сети или `/поиск-сети` для просмотра доступных сетей.",
            color=Config.EMBED_COLOR_ERROR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Проверяем, есть ли уже канал с этой сетью на текущем сервере (1 сеть = 1 сервер)
    # Исключение для привилегированного сервера
    privileged_guild_id = 1387900625324478506
    current_guild_id = interaction.guild.id
    
    if current_guild_id != privileged_guild_id:
        for existing_channel_id, existing_channel_info in linked_channels.items():
            if (existing_channel_info['network'] == network_name and 
                existing_channel_info.get('guild_id') == current_guild_id):
                embed = discord.Embed(
                    title="⚠️ Сеть уже используется",
                    description=f"На этом сервере уже есть канал, подключенный к сети `{network_name}`. \n\nОдин сервер может быть подключен только к одной сети через один канал.",
                    color=Config.EMBED_COLOR_WARNING
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
    
    # Добавляем канал в конфигурацию
    linked_channels[channel_id] = {
        'network': network_name,
        'guild_id': interaction.guild.id,
        'guild_name': interaction.guild.name,
        'channel_name': interaction.channel.name,
        'linked_at': datetime.utcnow().isoformat(),
        'linked_by': str(interaction.user.id)
    }
    
    save_channels_config(linked_channels)
    
    # Подсчитываем количество каналов в сети
    network_channels = [ch for ch in linked_channels.values() if ch['network'] == network_name]
    
    embed = discord.Embed(
        title="✅ Канал подключен",
        description=f"Канал успешно подключен к существующей сети `{network_name}`",
        color=Config.EMBED_COLOR_SUCCESS
    )
    embed.add_field(name="Каналов в сети", value=len(network_channels), inline=True)
    embed.add_field(name="Сеть", value=network_name, inline=True)
    embed.add_field(name="Подключил", value=interaction.user.mention, inline=True)
    
    await interaction.response.send_message(embed=embed)
    
    logger.info(f"Канал {interaction.guild.name}#{interaction.channel.name} связан с сетью '{network_name}' пользователем {interaction.user}")
    
    # Обновляем статус бота
    activity = discord.Activity(type=discord.ActivityType.watching, name=f"{len(linked_channels)} связанных каналов")
    await bot.change_presence(activity=activity)




# Slash команда для отключения каналов
@bot.tree.command(name="отключить", description="Отключить канал от сети")
async def slash_unlink_channel(interaction: discord.Interaction):
    """Slash команда для отключения канала от сети"""
    # Проверяем права
    if not interaction.user.guild_permissions.manage_channels:
        embed = discord.Embed(
            title="❌ Недостаточно прав",
            description="У вас нет прав для управления каналами.",
            color=Config.EMBED_COLOR_ERROR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    channel_id = str(interaction.channel.id)
    
    if channel_id not in linked_channels:
        embed = discord.Embed(
            title="❌ Канал не связан",
            description="Этот канал не связан ни с одной сетью.",
            color=Config.EMBED_COLOR_ERROR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    network_name = linked_channels[channel_id]['network']
    del linked_channels[channel_id]
    save_channels_config(linked_channels)
    
    embed = discord.Embed(
        title="✅ Канал отключен",
        description=f"Канал отключен от сети `{network_name}`",
        color=Config.EMBED_COLOR_SUCCESS
    )
    embed.add_field(name="Отключил", value=interaction.user.mention, inline=True)
    
    await interaction.response.send_message(embed=embed)
    
    logger.info(f"Канал {interaction.guild.name}#{interaction.channel.name} отключен от сети '{network_name}' пользователем {interaction.user}")
    
    # Обновляем статус бота
    activity = discord.Activity(type=discord.ActivityType.watching, name=f"{len(linked_channels)} связанных каналов")
    await bot.change_presence(activity=activity)

# Slash команда для проверки прав бота
@bot.tree.command(name="проверить_права", description="Проверить права бота в текущем канале")
async def slash_check_permissions(interaction: discord.Interaction):
    """Slash команда для проверки прав бота"""
    # Проверяем права пользователя
    if not interaction.user.guild_permissions.manage_channels:
        embed = discord.Embed(
            title="❌ Недостаточно прав",
            description="У вас нет прав для управления каналами.",
            color=Config.EMBED_COLOR_ERROR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Проверяем права бота
    has_permissions, missing_perms = await check_bot_permissions(interaction.channel, notify_admin=False)
    
    if has_permissions:
        embed = discord.Embed(
            title="✅ Все права предоставлены",
            description="Бот имеет все необходимые права в этом канале.",
            color=Config.EMBED_COLOR_SUCCESS
        )
        
        embed.add_field(
            name="🔧 Доступные права",
            value="• Отправка сообщений\n• Управление вебхуками\n• Чтение истории сообщений\n• Прикрепление файлов",
            inline=False
        )
    else:
        embed = discord.Embed(
            title="⚠️ Недостаточно прав у бота",
            description="Боту не хватает некоторых прав для корректной работы.",
            color=Config.EMBED_COLOR_WARNING
        )
        
        embed.add_field(
            name="❌ Отсутствующие права",
            value="\n".join([f"• {perm}" for perm in missing_perms]),
            inline=False
        )
        
        embed.add_field(
            name="🔧 Как исправить",
            value="1. Перейдите в настройки сервера\n2. Откройте раздел 'Роли'\n3. Найдите роль бота\n4. Предоставьте недостающие права",
            inline=False
        )
    
    embed.set_footer(text=f"Канал: #{interaction.channel.name}")
    await interaction.response.send_message(embed=embed, ephemeral=True)



# Slash команда для информации о боте
@bot.tree.command(name="поиск-сети", description="Показать все доступные сети для подключения")
async def slash_search_networks(interaction: discord.Interaction):
    """Slash команда для поиска доступных сетей"""
    try:
        # Получаем все уникальные сети
        networks = {}
        current_guild_id = interaction.guild.id
        
        for channel_id, channel_info in linked_channels.items():
            network_name = channel_info['network']
            guild_id = channel_info.get('guild_id')
            guild_name = channel_info.get('guild_name', 'Неизвестно')
            channel_name = channel_info.get('channel_name', 'Неизвестно')
            
            # Группируем по сетям
            if network_name not in networks:
                networks[network_name] = []
            
            networks[network_name].append({
                'guild_id': guild_id,
                'guild_name': guild_name,
                'channel_name': channel_name,
                'is_current_guild': guild_id == current_guild_id
            })
        
        if not networks:
            embed = discord.Embed(
                title="🔍 Поиск сетей",
                description="В данный момент нет доступных сетей для подключения.",
                color=Config.EMBED_COLOR_DEFAULT
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        embed = discord.Embed(
            title="🔍 Доступные сети",
            description="Список всех активных сетей:",
            color=Config.EMBED_COLOR_DEFAULT
        )
        
        for network_name, channels in networks.items():
            # Проверяем, есть ли уже канал с этой сетью на текущем сервере
            has_current_guild = any(ch['is_current_guild'] for ch in channels)
            
            if has_current_guild:
                status = "🔗 Уже подключен"
            else:
                status = "✅ Доступен для подключения"
            
            # Подсчитываем количество уникальных серверов
            unique_guilds = set()
            for ch in channels:
                if ch['guild_id'] and ch['guild_name'] != 'Неизвестно':
                    unique_guilds.add(ch['guild_id'])
            
            server_count = len(unique_guilds)
            
            embed.add_field(
                name=f"🌐 {network_name}",
                value=f"{status}\n📊 Серверов в сети: **{server_count}**",
                inline=True
            )
        
        embed.set_footer(text="Используйте /связать <имя_сети> для подключения к сети")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except Exception as e:
        logger.error(f"Ошибка в команде поиск-сети: {e}")
        embed = discord.Embed(
            title="❌ Ошибка",
            description="Произошла ошибка при поиске сетей.",
            color=Config.EMBED_COLOR_ERROR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="бот-инфо", description="Показать информацию о боте")
async def slash_bot_info(interaction: discord.Interaction):
    """Slash команда для отображения информации о боте"""
    # Получаем пинг бота
    ping = round(bot.latency * 1000)
    
    embed = discord.Embed(
        title="🤖 Информация о боте",
        description="Relay Bot - межсерверный мост для каналов с поддержкой RelayRU и RelayEN сетей",
        color=Config.EMBED_COLOR_INFO
    )
    
    embed.add_field(
        name="📊 Статистика",
        value=f"🏓 Пинг: {ping}ms\n🌐 Серверов: {len(bot.guilds)}\n👥 Пользователей: {len(bot.users)}",
        inline=True
    )
    
    embed.add_field(
        name="👨‍💻 Разработчик",
        value="brqden",
        inline=True
    )
    
    embed.add_field(
        name="⚡ Возможности",
        value="• Межсерверные сети каналов\n• Пересылка сообщений и файлов\n• Автоматический мониторинг прав\n• Антиспам защита\n• Уведомления о подключениях/отключениях\n• Система чёрного списка\n• Система уровней с отображением рангов\n• Красивое оформление сообщений",
        inline=False
    )
    
    embed.add_field(
        name="📋 Основные команды",
        value="`/создать-сеть` - создать новую сеть\n`/связать` - подключить канал к существующей сети\n`/отключить` - отключить канал\n`/поиск-сети` - показать доступные сети\n`/проверить_права` - проверить права бота\n\n💡 **Важно:** Название сети может быть любым и не обязательно должно совпадать с названием канала!",
        inline=False
    )
    
    embed.set_thumbnail(url=bot.user.display_avatar.url)
    embed.set_footer(text=f"Запрошено пользователем {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
    
    await interaction.response.send_message(embed=embed)

# Flask API для статистики
app = Flask(__name__)
CORS(app)  # Разрешаем CORS для веб-сайта

@app.route('/api/stats')
def get_bot_stats():
    """Возвращает статистику бота в JSON формате"""
    try:
        # Подсчитываем статистику
        guild_count = len(bot.guilds)
        user_count = sum(guild.member_count for guild in bot.guilds)
        
        # Подсчитываем количество связанных каналов
        channels_config = load_channels_config()
        linked_channels = len(channels_config)
        
        # Подсчитываем количество уникальных сетей
        networks = set()
        for channel_data in channels_config.values():
            if isinstance(channel_data, dict) and 'network' in channel_data:
                networks.add(channel_data['network'])
            elif isinstance(channel_data, str):
                networks.add(channel_data)
        active_networks = len(networks)
        
        # Примерное количество сообщений (можно добавить счетчик в будущем)
        message_count = linked_channels * 1000  # Примерная оценка
        
        stats = {
            'servers': guild_count,
            'users': user_count,
            'messages': message_count,
            'networks': active_networks,
            'linked_channels': linked_channels,
            'uptime': 'Online',
            'last_updated': datetime.utcnow().isoformat()
        }
        
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}")
        return jsonify({
            'servers': 0,
            'users': 0,
            'messages': 0,
            'networks': 0,
            'error': 'Не удалось получить статистику'
        }), 500

def run_flask():
    """Запускает Flask сервер в отдельном потоке"""
    app.run(host='0.0.0.0', port=25758, debug=False)

# Запуск бота
if __name__ == "__main__":
    if not Config.DISCORD_TOKEN:
        logger.error("❌ Не найден токен Discord бота!")
        logger.error("Создайте файл .env и добавьте: DISCORD_TOKEN=ваш_токен")
        logger.error("Или установите переменную окружения DISCORD_TOKEN")
        exit(1)
    
    try:
        # Инициализируем чёрный список
        if Config.BLACKLIST_ENABLED:
            blacklist = load_blacklist()
            logger.info(f"Загружен чёрный список: {len(blacklist)} пользователей")
        
        # Инициализируем систему уровней
        if Config.LEVELS_ENABLED:
            load_levels()
            logger.info(f"Система уровней инициализирована")
        
        # Запускаем Flask API в отдельном потоке
        logger.info("Запуск Flask API сервера...")
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        
        logger.info("Запуск Discord бота...")
        bot.run(Config.DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
        exit(1)