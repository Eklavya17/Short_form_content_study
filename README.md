# RQ3 Short-Video Feed Selection Study

This pilot measures when viewers continue or skip short videos, both at annotated pause points and during uninterrupted playback.

## App links

| View | Public URL | Local URL |
| --- | --- | --- |
| Participant study | [Open study](https://short-form-content-study.onrender.com/participant) | [Open local study](http://127.0.0.1:5001/participant) |
| Debug demo | [Open debug view](https://short-form-content-study.onrender.com/) | [Open local debug view](http://127.0.0.1:5001/) |

The local links use port `5001` and require the app to be running locally or an SSH tunnel to that port.

## Database connection

```bash
export RQ3_DATABASE_URL="<External Database URL from the database page on Render; never commit it>"
```

## Participant results

### List all participants

```bash
python -m rq3.admin list
```

### Inspect a particular participant

```bash
python -m rq3.admin show 1
```
