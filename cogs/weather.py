import asyncio
import json
import logging
import os
import unicodedata
# from collections import defaultdict
from datetime import datetime, time
from typing import Any, Dict, List, Optional

import aiohttp
import cairosvg
import discord
import requests
from discord.ext import commands, tasks
from discord.ext.commands import Context


class CitySelectionView(discord.ui.View):
    def __init__(self, cities: List[str], callback):
        super().__init__()
        self.callback = callback
        for city in cities:
            self.add_item(discord.ui.Button(label=city, style=discord.ButtonStyle.primary, custom_id=city))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await interaction.response.defer()
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(view=self)
        await self.callback(interaction, interaction.data['custom_id'])
        return True


class Weather(commands.Cog, name="weather"):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.parent_path = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
        self.region_data = self.load_region_data()
        self.update_weather_data.start()

    def load_region_data(self) -> Dict[str, Any]:
        try:
            with open(f"{self.parent_path}/region_code.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.error(f"failed to load region code file: {e}")
            return {}

    async def get_weather_data(self, city_code: str) -> Optional[Dict[str, Any]]:
        url = f"https://weather.tsukumijima.net/api/forecast/city/{city_code}"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logging.error(f"API request error: {response.status}")
                        return None
            except aiohttp.ClientError as e:
                logging.error(f"Network error: {e}")
                return None

    @commands.hybrid_command(
        name="forecast",
        description="現在の天気予報を表示します",
    )
    async def forecast(self, context: Context, prefecture: str) -> None:
        if prefecture not in self.region_data:
            await context.send("無効な都道府県名です。正しい都道府県名を入力してください。")
            return

        prefecture_data = self.region_data[prefecture]

        if not isinstance(prefecture_data, dict):
            await context.send("予期せぬデータ形式です。管理者に連絡してください。")
            return

        if len(prefecture_data) == 1:  # 都市が1つしかない場合
            city = list(prefecture_data.keys())[0]
            await self.show_weather(context, prefecture_data[city], prefecture, city)
        else:
            view = CitySelectionView(
                list(prefecture_data.keys()),
                lambda i, c: self.city_selected_forecast(i, context, prefecture, c)
            )
            await context.send(f"{prefecture}の地域を選択してください：", view=view)

    async def city_selected_forecast(
        self,
        interaction: discord.Interaction,
        original_context: Context,
        prefecture: str,
        city: str
    ) -> None:
        city_code = self.region_data[prefecture][city]
        await self.show_weather(original_context, city_code, prefecture, city)

    @commands.hybrid_command(
        name="addregion",
        description="サーバーに地域を追加します",
    )
    @commands.has_permissions(administrator=True)
    async def add_region(self, context: Context, prefecture: str) -> None:
        if prefecture not in self.region_data:
            await context.send("無効な都道府県名です。")
            return

        prefecture_data = self.region_data[prefecture]

        if not isinstance(prefecture_data, dict):
            await context.send("予期せぬデータ形式です。管理者に連絡してください。")
            return

        if len(prefecture_data) == 1:
            city = list(prefecture_data.keys())[0]
            await self.city_selected_add(context, prefecture, city)
        else:
            view = CitySelectionView(list(prefecture_data.keys()), lambda i, c: self.city_selected_add(i, context, prefecture, c))
            await context.send(f"{prefecture}の地域を選択してください：", view=view)

    async def city_selected_add(
        self,
        interaction_or_context: discord.Interaction | Context,
        original_context: Context,
        prefecture: str,
        city: str
    ) -> None:
        guild_id = original_context.guild.id
        city_code = self.region_data[prefecture][city]

        # Check if the region is already added
        existing_region = await self.bot.database.fetchone(
            "SELECT 1 FROM server_regions WHERE server_id = ? AND region_code = ?",
            (guild_id, city_code)
        )

        if not existing_region:
            await self.bot.database.execute(
                "INSERT INTO server_regions (server_id, region_code) VALUES (?, ?)",
                (guild_id, city_code)
            )
            await self.bot.database.commit()
            embed1 = discord.Embed(
                title="地域追加完了",
                description=f"{prefecture}({city})をこのサーバーに追加しました。",
                color=discord.Color.green()
            )

        if isinstance(interaction_or_context, discord.Interaction):
            message = f"{prefecture}({city})は既にこのサーバーに追加されています。"
            embed2 = discord.Embed(description=message, color=discord.Color.green())
            await interaction_or_context.edit_original_response(embed=embed2, view=None)
        else:
            await interaction_or_context.send(embed=embed1)

    @commands.hybrid_command(
        name="removeregion",
        description="サーバーから地域を削除します",
    )
    @commands.has_permissions(administrator=True)
    async def remove_region(self, context: commands.Context, prefecture: str, city: str) -> None:
        if prefecture not in self.region_data or city not in self.region_data[prefecture]:
            await context.send("無効な都道府県名または市区町村名です。")
            return

        city_code = self.region_data[prefecture][city]
        await self.bot.database.execute(
            "DELETE FROM server_regions WHERE server_id = ? AND region_code = ?",
            (context.guild.id, city_code)
        )
        await self.bot.database.commit()
        embed = discord.Embed(
            title="地域削除完了",
            description=f"{prefecture}({city})をこのサーバーの地域から削除しました。",
            color=discord.Color.red()
        )
        await context.send(embed=embed)

    @commands.hybrid_command(
        name="listregions",
        description="サーバーに登録されている地域の一覧を表示します",
    )
    async def list_regions(self, context: commands.Context) -> None:
        cursor = await self.bot.database.execute(
            "SELECT region_code FROM server_regions WHERE server_id = ?",
            (context.guild.id,)
        )
        region_codes = await cursor.fetchall()

        if not region_codes:
            await context.send("このサーバーには登録された地域がありません。")
            return

        registered_regions = []
        for (region_code,) in region_codes:
            for prefecture, cities in self.region_data.items():
                for city, code in cities.items():
                    if code == region_code:
                        registered_regions.append(f"{prefecture} - {city}")
                        break
                if registered_regions[-1].startswith(prefecture):
                    break

        embed = discord.Embed(
            title="登録された地域一覧",
            description="\n".join(registered_regions),
            color=discord.Color.blue()
        )
        await context.send(embed=embed)

    def process_weather_data(self, weather_data: Dict[str, Any]) -> Optional[discord.Embed]:
        if not weather_data or 'forecasts' not in weather_data:
            return None

        today_forecast = weather_data['forecasts'][0]
        date = datetime.strptime(today_forecast['date'], '%Y-%m-%d').strftime('%Y年%m月%d日')

        embed = discord.Embed(
            title=f"{weather_data['location']['prefecture']} ({weather_data['location']['city']})の天気予報({date})",
            description=today_forecast['detail']['weather'].replace('\u3000', ' '),
            color=0x3498db
        )

        max_temp = today_forecast['temperature']['max']['celsius']
        min_temp = today_forecast['temperature']['min']['celsius']

        if max_temp:
            embed.add_field(name="最高気温", value=f"{max_temp}℃", inline=True)
        if min_temp:
            embed.add_field(name="最低気温", value=f"{min_temp}℃", inline=True)

        def process_time(time: str) -> str:
            return f"{int(time[1:3])}時～{int(time[4:6])}時"

        rain_probs = today_forecast['chanceOfRain']
        valid_probs = [f"{process_time(time)}: {prob}" for time, prob in rain_probs.items() if prob != '--%']
        if valid_probs:
            embed.add_field(name="降水確率", value='\n'.join(valid_probs), inline=False)

        wind = today_forecast['detail'].get('wind', 'データなし')
        wave = today_forecast['detail'].get('wave', 'データなし')
        wave = unicodedata.normalize('NFKC', wave)
        embed.add_field(name="風", value=wind.replace("　", " "), inline=True)
        embed.add_field(name="波", value=wave, inline=True)

        if weather_data['description']['headlineText']:
            embed.add_field(name="警報・注意報", value=weather_data['description']['headlineText'], inline=False)

        return embed

    async def show_weather(self, context, city_code: str, prefecture: str, city: str):
        weather_data = await self.get_cached_weather_data(city_code)
        if weather_data is None:
            await self.send_or_edit_message(context, "天気データの取得に失敗しました。")
            return

        embed = self.process_weather_data(weather_data)
        if embed is None:
            await self.send_or_edit_message(context, "天気データの処理に失敗しました。")
            return

        logo_link = weather_data['forecasts'][0]['image']['url']
        self.process_image(logo_link)
        file = discord.File("temp.png", filename="temp.png")
        embed.set_thumbnail(url="attachment://temp.png")

        if isinstance(context, discord.Interaction):
            await context.edit_original_response(content="", embed=embed, attachments=[file])
        else:
            await context.send(embed=embed, file=file)

        if os.path.exists("temp.png"):
            os.remove("temp.png")

    async def send_or_edit_message(self, context, content="", **kwargs):
        if isinstance(context, discord.Interaction):
            if context.response.is_done():
                await context.edit_original_response(content=content, **kwargs)
            else:
                await context.response.send_message(content=content, **kwargs)
        else:
            await context.send(content=content, **kwargs)

        if os.path.exists("temp.png"):
            os.remove("temp.png")

    def process_image(self, url: str) -> None:
        response = requests.get(url)
        if response.status_code != 200:
            print(f"Failed to download SVG from {url}")
            return

        cairosvg.svg2png(bytestring=response.content, write_to="temp.png")

    async def cache_weather_data(self, city_code: str, weather_data: Dict[str, Any]):
        await self.bot.database.execute(
            "INSERT OR REPLACE INTO weather_cache (city_code, data, timestamp, date) VALUES (?, ?, ?, ?)",
            (city_code, json.dumps(weather_data), datetime.now().isoformat(), datetime.now().date().isoformat())
        )
        await self.bot.database.commit()

    async def get_cached_weather_data(self, city_code: str) -> Optional[Dict[str, Any]]:
        result = await self.bot.database.fetchone(
            "SELECT data, timestamp, date FROM weather_cache WHERE city_code = ?",
            (city_code,)
        )

        if result:
            data, timestamp, cache_date = result
            cached_date = datetime.fromisoformat(cache_date).date()
            current_date = datetime.now().date()

            if cached_date == current_date:
                cached_data = json.loads(data)
                if self.is_complete_weather_data(cached_data):
                    return cached_data

        weather_data = await self.get_weather_data(city_code)
        if weather_data:
            await self.cache_weather_data(city_code, weather_data)
        return weather_data

    def is_complete_weather_data(self, weather_data: Dict[str, Any]) -> bool:
        if not weather_data or 'forecasts' not in weather_data:
            return False

        today_forecast = weather_data['forecasts'][0]

        required_fields = [
            'date',
            'detail',
            'temperature',
            'chanceOfRain',
        ]

        for field in required_fields:
            if field not in today_forecast:
                return False

        if not today_forecast['temperature']['max'] or not today_forecast['temperature']['min']:
            return False

        rain_probs = today_forecast['chanceOfRain']
        if not all(prob != '--%' for prob in rain_probs.values()):
            return False

        return True

    @tasks.loop(time=time(hour=0, minute=5))  # 毎日午前0時5分に実行
    async def update_weather_data(self):
        regions = await self.bot.database.fetchall("SELECT DISTINCT region_code FROM server_regions")

        for region in regions:
            city_code = region[0]
            weather_data = await self.get_weather_data(city_code)
            if weather_data:
                await self.cache_weather_data(city_code, weather_data)
            await asyncio.sleep(1)

    @tasks.loop(hours=1)
    async def notify_warning(self):
        server_regions = await self.bot.database.fetchall("SELECT server_id, region_code FROM server_regions")

        for server_id, region_code in server_regions:
            weather_data = await self.get_cached_weather_data(region_code)
            if weather_data and weather_data['description']['headlineText']:
                guild = self.bot.get_guild(server_id)
                if guild:
                    channel = guild.system_channel or guild.text_channels[0]
                    embed = discord.Embed(
                        title=f"{weather_data['location']['prefecture']} ({weather_data['location']['city']})の警報・注意報",
                        description=weather_data['description']['headlineText'],
                        color=0xFF0000
                    )
                    await channel.send(embed=embed)


async def setup(bot) -> None:
    await bot.add_cog(Weather(bot))
