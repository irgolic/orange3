# pylint: disable=expression-not-assigned, pointless-statement

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix, coo_matrix, csc_matrix

from Orange.data import Table, Domain, ContinuousVariable
from Orange.preprocess import Normalize
from benchmark.base import Benchmark, benchmark


def table(rows, cols):
    return Table.from_numpy(  # pylint: disable=W0201
        Domain([ContinuousVariable(str(i)) for i in range(cols)]),
        np.random.RandomState(0).rand(rows, cols))


class BenchPandas(Benchmark):
    arr = None
    table = None
    tdf = None
    df = None  # pylint: disable=invalid-name
    domain = None

    def setUp(self):
        if self.table is None:
            self.skipTest("Base class")

    @benchmark(number=5)
    def bench_create_table(self):
        Table.from_numpy(
            self.domain,
            self.arr
        )

    @benchmark(number=5)
    def bench_create_orangedf(self):
        self.table.to_pandas_dfs()

    @benchmark(number=5)
    def bench_revert_orangedf(self):
        self.tdf.to_orange_table()

    @benchmark(number=5)
    def bench_multiply_table(self):
        self.arr * 42

    @benchmark(number=5)
    def bench_multiply_df(self):
        self.df * 42

    @benchmark(number=5)
    def bench_multiply_df_numpy(self):
        self.df.values * 42

    @benchmark(number=5)
    def bench_multiply_orangedf(self):
        self.tdf * 42

    @benchmark(number=5)
    def bench_multiply_orangedf_numpy(self):
        self.tdf.values * 42

    @benchmark(number=5)
    def bench_normalize_table(self):
        Normalize()(self.table)

    @benchmark(number=5)
    def bench_normalize_df(self):
        # automatically column-wise
        (self.df - self.df.mean()) / self.df.std()

    @benchmark(number=5)
    def bench_normalize_df_numpy(self):
        values = self.df.values
        (values - np.mean(values,
                          axis=0)) / np.std(values,
                                            axis=0)

    @benchmark(number=5)
    def bench_normalize_orangedf(self):
        # automatically column-wise
        (self.tdf - self.tdf.mean()) / self.tdf.std()

    @benchmark(number=5)
    def bench_normalize_orangedf_numpy(self):
        values = self.tdf.values
        (values - np.mean(values,
                          axis=0)) / np.std(values,
                                            axis=0)


class BenchPandasDense(BenchPandas):
    @classmethod
    def setUpClass(cls):
        cols = 100
        rows = 100000
        cont = [ContinuousVariable(str(i)) for i in range(cols)]
        cls.domain = Domain(cont)
        print('creating numpy arr')
        cls.arr = np.random.RandomState(0).randint(0, 2, (rows, len(cls.domain)))
        print('creating table')
        cls.table = Table.from_numpy(
            cls.domain,
            cls.arr
        )
        print('converting table to dataframe')
        cls.tdf, _, _ = cls.table.to_pandas_dfs()
        print('converting back to table')
        cls.tdf.to_orange_table()
        print('creating natural df')
        cls.df = pd.DataFrame(cls.arr)

    @benchmark(number=5)
    def bench_create_df(self):
        pd.DataFrame(self.arr)


class BenchPandasSparse(BenchPandas):
    @classmethod
    def setUpClass(cls):
        cols = 100
        rows = 100000
        cont = [ContinuousVariable(str(i)) for i in range(cols)]
        cls.domain = Domain(cont)

        cls.arr = arr = np.random.RandomState(0).randint(0, 2, (rows, len(cls.domain)))
        print('Dense size:', arr.data.nbytes)
        cls.arr = arr = csc_matrix(arr)
        print('CSC sparse size:', arr.data.nbytes)
        arr2 = coo_matrix(arr)
        print("COO sparse size:", arr2.data.nbytes)
        arr2 = csr_matrix(arr)
        print("CSR sparse size:", arr2.data.nbytes)
        cls.table = Table.from_numpy(
            cls.domain,
            arr
        )
        print('Sparse size in table:', cls.table.X.data.nbytes)
        cls.df = pd.DataFrame.sparse.from_spmatrix(arr)
        print('Sparse size in natural df:', sum(cls.df[i].nbytes for i in cls.df))
        cls.tdf, _, _ = cls.table.to_pandas_dfs()
        print('Sparse size in Orange df:', sum(cls.tdf[i].nbytes for i in cls.tdf))
        table_back = cls.tdf.to_orange_table()
        print('Sparse size converted back:', table_back.X.data.nbytes)

    @benchmark(number=5)
    def bench_create_df(self):
        pd.DataFrame.sparse.from_spmatrix(self.arr)
