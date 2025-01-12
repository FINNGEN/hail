import random
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
import asyncio
import pytest
from hailtop.utils import secret_alnum_string
from hailtop.aiotools import LocalAsyncFS, RouterAsyncFS, UnexpectedEOFError
from hailtop.aiotools.s3asyncfs import S3AsyncFS
from hailtop.aiotools.azurefs import AzureAsyncFS
from hailtop.aiogoogle import GoogleStorageAsyncFS


@pytest.fixture(params=['file', 'gs', 's3', 'hail-az', 'router/file', 'router/gs', 'router/s3', 'router/hail-az'])
async def filesystem(request):
    token = secret_alnum_string()

    with ThreadPoolExecutor() as thread_pool:
        if request.param.startswith('router/'):
            fs = RouterAsyncFS(
                'file', [LocalAsyncFS(thread_pool),
                         GoogleStorageAsyncFS(),
                         S3AsyncFS(thread_pool),
                         AzureAsyncFS()])
        elif request.param == 'file':
            fs = LocalAsyncFS(thread_pool)
        elif request.param.endswith('gs'):
            fs = GoogleStorageAsyncFS()
        elif request.param.endswith('s3'):
            fs = S3AsyncFS(thread_pool)
        else:
            assert request.param.endswith('hail-az')
            fs = AzureAsyncFS()
        async with fs:
            if request.param.endswith('file'):
                base = f'/tmp/{token}/'
            elif request.param.endswith('gs'):
                bucket = os.environ['HAIL_TEST_GCS_BUCKET']
                base = f'gs://{bucket}/tmp/{token}/'
            elif request.param.endswith('s3'):
                bucket = os.environ['HAIL_TEST_S3_BUCKET']
                base = f's3://{bucket}/tmp/{token}/'
            else:
                assert request.param.endswith('hail-az')
                account = os.environ['HAIL_TEST_AZURE_ACCOUNT']
                container = os.environ['HAIL_TEST_AZURE_CONTAINER']
                base = f'hail-az://{account}/{container}/tmp/{token}/'

            await fs.mkdir(base)
            sema = asyncio.Semaphore(50)
            async with sema:
                yield (sema, fs, base)
                await fs.rmtree(sema, base)
            assert not await fs.isdir(base)


@pytest.fixture
async def local_filesystem(request):
    token = secret_alnum_string()

    with ThreadPoolExecutor() as thread_pool:
        async with LocalAsyncFS(thread_pool) as fs:
            base = f'/tmp/{token}/'
            await fs.mkdir(base)
            sema = asyncio.Semaphore(50)
            async with sema:
                yield (sema, fs, base)
                await fs.rmtree(sema, base)
            assert not await fs.isdir(base)


@pytest.fixture(params=['small', 'multipart', 'large'])
def file_data(request):
    if request.param == 'small':
        return [b'foo']
    elif request.param == 'multipart':
        return [b'foo', b'bar', b'baz']
    else:
        assert request.param == 'large'
        return [secrets.token_bytes(1_000_000)]


@pytest.mark.asyncio
async def test_write_read(filesystem, file_data):
    sema, fs, base = filesystem

    file = f'{base}foo'

    async with await fs.create(file) as f:
        for b in file_data:
            await f.write(b)

    expected = b''.join(file_data)
    async with await fs.open(file) as f:
        actual = await f.read()

    assert expected == actual


@pytest.mark.asyncio
async def test_open_from(filesystem):
    sema, fs, base = filesystem

    file = f'{base}foo'

    async with await fs.create(file) as f:
        await f.write(b'abcde')

    async with await fs.open_from(file, 2) as f:
        r = await f.read()
        assert r == b'cde'


@pytest.mark.asyncio
async def test_open_nonexistent_file(filesystem):
    sema, fs, base = filesystem

    file = f'{base}foo'

    try:
        async with await fs.open(file) as f:
            await f.read()
    except FileNotFoundError:
        pass
    else:
        assert False


@pytest.mark.asyncio
async def test_open_from_nonexistent_file(filesystem):
    sema, fs, base = filesystem

    file = f'{base}foo'

    try:
        async with await fs.open_from(file, 2) as f:
            await f.read()
    except FileNotFoundError:
        pass
    else:
        assert False


@pytest.mark.asyncio
async def test_read_from(filesystem):
    sema, fs, base = filesystem

    file = f'{base}foo'

    await fs.write(file, b'abcde')
    r = await fs.read_from(file, 2)
    assert r == b'cde'


@pytest.mark.asyncio
async def test_read_range(filesystem):
    sema, fs, base = filesystem

    file = f'{base}foo'

    await fs.write(file, b'abcde')

    r = await fs.read_range(file, 2, 2)
    assert r == b'c'

    r = await fs.read_range(file, 2, 4)
    assert r == b'cde'

    try:
        await fs.read_range(file, 2, 10)
    except UnexpectedEOFError:
        pass
    else:
        assert False


@pytest.mark.asyncio
async def test_write_read_range(filesystem, file_data):
    sema, fs, base = filesystem

    file = f'{base}foo'

    async with await fs.create(file) as f:
        for b in file_data:
            await f.write(b)

    pt1 = random.randint(0, len(file_data))
    pt2 = random.randint(0, len(file_data))
    start = min(pt1, pt2)
    end = max(pt1, pt2)

    expected = b''.join(file_data)[start:end+1]
    actual = await fs.read_range(file, start, end)  # end is inclusive

    assert expected == actual


@pytest.mark.asyncio
async def test_isfile(filesystem):
    sema, fs, base = filesystem

    file = f'{base}foo'

    # doesn't exist yet
    assert not await fs.isfile(file)

    await fs.touch(file)

    assert await fs.isfile(file)


@pytest.mark.asyncio
async def test_isdir(filesystem):
    sema, fs, base = filesystem

    # mkdir with trailing slash
    dir = f'{base}dir/'
    await fs.mkdir(dir)

    await fs.touch(f'{dir}foo')

    # can't test this until after creating foo
    assert await fs.isdir(dir)

    # mkdir without trailing slash
    dir2 = f'{base}dir2'
    await fs.mkdir(dir2)

    await fs.touch(f'{dir2}/foo')

    assert await fs.isdir(dir)


@pytest.mark.asyncio
async def test_isdir_subdir_only(filesystem):
    sema, fs, base = filesystem

    dir = f'{base}dir/'
    await fs.mkdir(dir)

    subdir = f'{dir}subdir/'
    await fs.mkdir(subdir)

    await fs.touch(f'{subdir}foo')

    # can't test this until after creating foo
    assert await fs.isdir(dir)
    assert await fs.isdir(subdir)


@pytest.mark.asyncio
async def test_remove(filesystem):
    sema, fs, base = filesystem

    file = f'{base}foo'

    await fs.touch(file)
    assert await fs.isfile(file)

    await fs.remove(file)

    assert not await fs.isfile(file)


@pytest.mark.asyncio
async def test_rmtree(filesystem):
    sema, fs, base = filesystem

    dir = f'{base}foo/'

    await fs.mkdir(dir)
    await fs.touch(f'{dir}a')
    await fs.touch(f'{dir}b')

    assert await fs.isdir(dir)

    await fs.rmtree(sema, dir)

    assert not await fs.isdir(dir)


@pytest.mark.asyncio
async def test_statfile_nonexistent_file(filesystem):
    sema, fs, base = filesystem

    with pytest.raises(FileNotFoundError):
        await fs.statfile(f'{base}foo')


@pytest.mark.asyncio
async def test_statfile_directory(filesystem):
    sema, fs, base = filesystem

    await fs.mkdir(f'{base}dir/')
    await fs.touch(f'{base}dir/foo')

    with pytest.raises(FileNotFoundError):
        # statfile raises FileNotFound on directories
        await fs.statfile(f'{base}dir')


@pytest.mark.asyncio
async def test_statfile(filesystem):
    sema, fs, base = filesystem

    n = 37
    file = f'{base}bar'
    await fs.write(file, secrets.token_bytes(n))
    status = await fs.statfile(file)
    assert await status.size() == n

@pytest.mark.asyncio
async def test_listfiles(filesystem):
    sema, fs, base = filesystem

    with pytest.raises(FileNotFoundError):
        await fs.listfiles(f'{base}does/not/exist')

    with pytest.raises(FileNotFoundError):
        await fs.listfiles(f'{base}does/not/exist', recursive=True)

    # create the following directory structure in base:
    # foobar
    # foo/a
    # foo/b/c
    a = f'{base}foo/a'
    b = f'{base}foo/b/'
    c = f'{base}foo/b/c'
    await fs.touch(f'{base}foobar')
    await fs.mkdir(f'{base}foo/')
    await fs.touch(a)
    await fs.mkdir(b)
    await fs.touch(c)

    async def listfiles(dir, recursive):
        return {(await entry.url(), await entry.is_file()) async for entry in await fs.listfiles(dir, recursive)}

    assert await listfiles(f'{base}foo/', recursive=True) == {(a, True), (c, True)}
    assert await listfiles(f'{base}foo/', recursive=False) == {(a, True), (b, False)}

    # without trailing slash
    assert await listfiles(f'{base}foo', recursive=True) == {(a, True), (c, True)}
    assert await listfiles(f'{base}foo', recursive=False) == {(a, True), (b, False)}

    # test FileListEntry.status raises on directory
    async for entry in await fs.listfiles(f'{base}foo/', recursive=False):
        if await entry.is_dir():
            with pytest.raises(IsADirectoryError):
                await entry.status()
        else:
            stat = await entry.status()
            assert await stat.size() == 0

@pytest.mark.asyncio
@pytest.mark.parametrize("permutation", [
    None,
    [0, 1, 2],
    [0, 2, 1],
    [1, 2, 0],
    [2, 1, 0]
])
async def test_multi_part_create(filesystem, permutation):
    sema, fs, base = filesystem

    # S3 has a minimum part size (except for the last part) of 5MiB
    if base.startswith('s3'):
        min_part_size = 5 * 1024 * 1024
        part_data_size = [min_part_size, min_part_size, min_part_size]
    else:
        part_data_size = [8192, 600, 20000]
    part_data = [secrets.token_bytes(s) for s in part_data_size]

    s = 0
    part_start = []
    for b in part_data:
        part_start.append(s)
        s += len(b)

    path = f'{base}a'
    async with await fs.multi_part_create(sema, path, len(part_data)) as c:
        async def create_part(i):
            async with await c.create_part(i, part_start[i]) as f:
                await f.write(part_data[i])

        if permutation:
            # do it in a fixed order
            for i in permutation:
                await create_part(i)
        else:
            # do in parallel
            await asyncio.gather(*[
                create_part(i) for i in range(len(part_data))])

    expected = b''.join(part_data)
    async with await fs.open(path) as f:
        actual = await f.read()
    assert expected == actual
