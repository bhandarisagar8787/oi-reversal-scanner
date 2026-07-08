from app.database.models import Bar

bar = Bar(
    symbol="NIFTY",
    ts_utc=123456,
    open=100,
    high=105,
    low=95,
    close=102,
    volume=1000,
    open_interest=5500,
)

print(bar)